"""Polite HTTP client: identifies itself, honours robots.txt, rate-limits, no retries on 4xx.

Live collection is opt-in (--live). In the Phase 1 cloud session every source host
was denied by the environment's network policy, so this path is unit-tested with a
stub opener rather than against the real services. See docs/feasibility.md.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.robotparser
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

DEFAULT_UA = "SolvantSignalEngine/0.1 (+https://solvant.io)"


class FetchBlocked(RuntimeError):
    """Raised when robots.txt disallows a path or the network refuses the host."""


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

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                req = urllib.request.Request(f"{base}/robots.txt", headers={"User-Agent": self.user_agent})
                with self._opener(req, 15) as resp:
                    rp.parse(resp.read().decode("utf-8", "replace").splitlines())
            except Exception:
                # Unknown robots policy: be conservative and allow only documented API paths,
                # which callers mark with check_robots=False.
                rp.parse(["User-agent: *", "Disallow: /"])
            self._robots[base] = rp
        return rp.can_fetch(self.user_agent, url)

    def get_json(self, url: str, check_robots: Optional[bool] = None) -> Any:
        if (self.check_robots if check_robots is None else check_robots) and not self._robots_allows(url):
            raise FetchBlocked(f"robots.txt disallows {url}")
        host = urlsplit(url).netloc
        wait = self.min_interval_s - (time.monotonic() - self._last.get(host, -1e9))
        if wait > 0:
            self._sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with self._opener(req, 30) as resp:
                body = resp.read()
        except Exception as exc:  # network policy denials surface here
            raise FetchBlocked(f"{host}: {exc}") from exc
        finally:
            self._last[host] = time.monotonic()
        return json.loads(body)
