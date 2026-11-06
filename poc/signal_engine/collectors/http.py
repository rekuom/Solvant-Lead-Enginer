"""Polite HTTP client: identifies itself, honours robots.txt, rate-limits, no retries on 4xx.

Every failure is classified so a *network-policy block* (our side) is never confused
with an *upstream refusal*, an *authentication requirement* or a *rate limit*
(their side). See `classify_error` and docs/validation-2a.md.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

DEFAULT_UA = "SolvantSignalEngine/0.1 (+https://solvant.io)"

# Failure kinds
PROXY_BLOCK = "proxy_block"            # our egress gateway refused CONNECT; upstream never contacted
DNS_BLOCKED = "dns_blocked"            # name did not resolve (policy or nonexistent host)
AUTH_REQUIRED = "auth_required"        # upstream 401 / 407-from-origin / login redirect
UPSTREAM_FORBIDDEN = "upstream_forbidden"  # upstream 403 (incl. bot protection)
RATE_LIMITED = "rate_limited"          # upstream 429
NOT_FOUND = "not_found"                # upstream 404 / 410
UPSTREAM_ERROR = "upstream_error"      # upstream 5xx / other HTTP status
TIMEOUT = "timeout"
ROBOTS_DISALLOWED = "robots_disallowed"
BAD_RESPONSE = "bad_response"          # 200 but not parseable as expected
OTHER = "other"


class FetchBlocked(RuntimeError):
    """Raised when a fetch cannot be completed. `.kind` says whose side the problem is on."""

    def __init__(self, message: str, kind: str = OTHER, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


def classify_error(exc: BaseException) -> tuple[str, Optional[int]]:
    """Map an exception from urllib to (kind, http_status)."""
    if isinstance(exc, urllib.error.HTTPError):  # a real response from the upstream server
        code = exc.code
        if code == 401:
            return AUTH_REQUIRED, code
        if code == 403:
            return UPSTREAM_FORBIDDEN, code
        if code == 429:
            return RATE_LIMITED, code
        if code in (404, 410):
            return NOT_FOUND, code
        return UPSTREAM_ERROR, code
    msg = str(getattr(exc, "reason", exc))
    if "Tunnel connection failed" in msg or "CONNECT tunnel failed" in msg:
        # urllib reports the proxy's CONNECT answer this way; the origin was never reached.
        code = None
        for tok in msg.split():
            if tok.isdigit():
                code = int(tok)
                break
        return PROXY_BLOCK, code
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.gaierror) or "Name or service not known" in msg or "getaddrinfo" in msg:
        return DNS_BLOCKED, None
    if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in msg:
        return TIMEOUT, None
    return OTHER, None


class PoliteClient:
    def __init__(
        self,
        min_interval_s: float = 2.0,
        user_agent: Optional[str] = None,
        opener: Optional[Callable[[urllib.request.Request, float], Any]] = None,
        check_robots: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.user_agent = user_agent or os.environ.get("SIGNAL_ENGINE_USER_AGENT", DEFAULT_UA)
        self._opener = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))
        self.check_robots = check_robots
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.max_retries_429 = 2

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            req = urllib.request.Request(f"{base}/robots.txt", headers={"User-Agent": self.user_agent})
            try:
                with self._opener(req, 15) as resp:
                    rp.parse(resp.read().decode("utf-8", "replace").splitlines())
            except Exception as exc:
                kind, status = classify_error(exc)
                if kind in (PROXY_BLOCK, DNS_BLOCKED, TIMEOUT):
                    # Could not reach the site at all: report that, do not pretend robots said no.
                    raise FetchBlocked(f"{parts.netloc}: robots.txt unreachable ({kind}): {exc}", kind, status) from exc
                if kind == NOT_FOUND:
                    rp.parse([])  # no robots.txt => no restrictions (RFC 9309)
                else:
                    rp.parse(["User-agent: *", "Disallow: /"])  # unknown policy => conservative
            self._robots[base] = rp
        return rp.can_fetch(self.user_agent, url)

    def get_json(self, url: str, check_robots: Optional[bool] = None) -> Any:
        if (self.check_robots if check_robots is None else check_robots) and not self._robots_allows(url):
            raise FetchBlocked(f"robots.txt disallows {url}", ROBOTS_DISALLOWED)
        host = urlsplit(url).netloc
        wait = self.min_interval_s - (time.monotonic() - self._last.get(host, -1e9))
        if wait > 0:
            self._sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        attempt = 0
        while True:
            try:
                with self._opener(req, 30) as resp:
                    body = resp.read()
                break
            except Exception as exc:
                kind, status = classify_error(exc)
                if kind == RATE_LIMITED and attempt < self.max_retries_429:
                    # Honour Retry-After (capped), else back off 10s, 20s.
                    retry_after = None
                    try:
                        retry_after = float(getattr(exc, "headers", {}).get("Retry-After"))
                    except (TypeError, ValueError):
                        pass
                    attempt += 1
                    self._sleep(min(30.0, retry_after if retry_after is not None else 10.0 * attempt))
                    continue
                raise FetchBlocked(f"{host}: {kind}: {exc}", kind, status) from exc
            finally:
                self._last[host] = time.monotonic()
        try:
            return json.loads(body)
        except ValueError as exc:
            raise FetchBlocked(f"{host}: response is not JSON", BAD_RESPONSE) from exc
