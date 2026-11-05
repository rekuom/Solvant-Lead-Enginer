"""Task 1 — network/access probe for the Phase 2A source domains.

For each endpoint, records: HTTP status, content type, redirect chain, final URL,
size, whether the body parses as JSON, and a failure *kind* that separates
  proxy_block / dns_blocked            (our environment's network policy)
  auth_required / upstream_forbidden   (the source refused us)
  rate_limited / not_found / upstream_error / timeout
Run from poc/:  python3 -m signal_engine.validate probe
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .collectors.http import DEFAULT_UA, classify_error

# Endpoints marked confirmed=False are documented-by-convention guesses that the probe
# itself is meant to confirm or refute; nothing downstream relies on them until it does.
ENDPOINTS: dict[str, list[dict[str, Any]]] = {
    "www.contractsfinder.service.gov.uk": [
        {"name": "robots", "url": "https://www.contractsfinder.service.gov.uk/robots.txt", "expect": "text", "confirmed": True},
        {"name": "ocds_search", "url": "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?publishedFrom={since}&publishedTo={today}&stages=tender&size=5", "expect": "json", "confirmed": True},
        {"name": "ocds_search_keyword", "url": "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?keyword=automation&publishedFrom={since}&publishedTo={today}&stages=tender&size=5", "expect": "json", "confirmed": False},
        {"name": "notice_page", "url": "https://www.contractsfinder.service.gov.uk/Notice/44159391-5279-46b1-8665-5c540f9e7086", "expect": "html", "confirmed": True},
    ],
    "www.find-tender.service.gov.uk": [
        {"name": "robots", "url": "https://www.find-tender.service.gov.uk/robots.txt", "expect": "text", "confirmed": True},
        {"name": "ocds_packages", "url": "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?updatedFrom={since}T00:00:00&stages=tender&limit=5", "expect": "json", "confirmed": True},
        {"name": "notice_page", "url": "https://www.find-tender.service.gov.uk/Notice/090524-2026", "expect": "html", "confirmed": True},
    ],
    "community.n8n.io": [
        {"name": "robots", "url": "https://community.n8n.io/robots.txt", "expect": "text", "confirmed": True},
        {"name": "jobs_category", "url": "https://community.n8n.io/c/jobs/13.json", "expect": "json", "confirmed": True},
        {"name": "topic", "url": "https://community.n8n.io/t/326857.json", "expect": "json", "confirmed": True},
        {"name": "search", "url": "https://community.n8n.io/search.json?q=%23jobs%20after%3A{since}", "expect": "json", "confirmed": True},
        {"name": "tos", "url": "https://community.n8n.io/tos", "expect": "html", "confirmed": True},
    ],
    "community.make.com": [
        {"name": "robots", "url": "https://community.make.com/robots.txt", "expect": "text", "confirmed": True},
        {"name": "hire_category", "url": "https://community.make.com/c/hire-a-pro/50.json", "expect": "json", "confirmed": True},
        {"name": "topic", "url": "https://community.make.com/t/97223.json", "expect": "json", "confirmed": True},
        {"name": "tos", "url": "https://community.make.com/tos", "expect": "html", "confirmed": True},
    ],
}


@dataclass
class ProbeResult:
    domain: str
    name: str
    url: str
    endpoint_confirmed_by_docs: bool
    ok: bool
    kind: str                       # "ok" or a failure kind
    blocked_by: str                 # "none" | "our_network_policy" | "source" | "unknown"
    status: Optional[int] = None
    content_type: Optional[str] = None
    redirects: list[str] = field(default_factory=list)
    final_url: Optional[str] = None
    bytes: int = 0
    parses_as_expected: Optional[bool] = None
    login_redirect: bool = False
    elapsed_ms: int = 0
    error: Optional[str] = None


class _RecordingRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        self.chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 (stdlib signature)
        self.chain.append(f"{code} -> {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_open(url: str, ua: str, timeout: float):
    rec = _RecordingRedirects()
    opener = urllib.request.build_opener(rec)
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json, text/html;q=0.8, */*;q=0.5"})
    resp = opener.open(req, timeout=timeout)
    return resp, rec.chain


_SIDE = {"proxy_block": "our_network_policy", "dns_blocked": "our_network_policy",
         "auth_required": "source", "upstream_forbidden": "source", "rate_limited": "source",
         "not_found": "source", "upstream_error": "source", "timeout": "unknown", "other": "unknown"}


def probe_url(domain: str, ep: dict[str, Any], since: str, today: str, ua: str = DEFAULT_UA,
              open_fn: Optional[Callable[[str, str, float], Any]] = None) -> ProbeResult:
    url = ep["url"].format(since=since, today=today)
    open_fn = open_fn or _default_open
    t0 = time.monotonic()
    res = ProbeResult(domain=domain, name=ep["name"], url=url, endpoint_confirmed_by_docs=ep["confirmed"],
                      ok=False, kind="other", blocked_by="unknown")
    try:
        resp, chain = open_fn(url, ua, 30)
        with resp:
            body = resp.read()
            res.status = getattr(resp, "status", None) or resp.getcode()
            res.content_type = resp.headers.get("Content-Type")
            res.final_url = resp.geturl()
        res.redirects = chain
        res.bytes = len(body)
        res.login_redirect = any(x in (res.final_url or "").lower() for x in ("/login", "/session", "/signin"))
        if ep["expect"] == "json":
            try:
                json.loads(body)
                res.parses_as_expected = True
            except ValueError:
                res.parses_as_expected = False
        else:
            res.parses_as_expected = True
        if res.login_redirect:
            res.kind, res.blocked_by = "auth_required", "source"
        elif res.parses_as_expected is False:
            res.kind, res.blocked_by = "bad_response", "source"
        else:
            res.ok, res.kind, res.blocked_by = True, "ok", "none"
    except Exception as exc:  # classify whose side the failure is on
        kind, status = classify_error(exc)
        res.kind, res.status, res.blocked_by = kind, status, _SIDE.get(kind, "unknown")
        res.error = f"{type(exc).__name__}: {exc}"[:300]
    res.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return res


def run_probe(since: str, open_fn=None, pause_s: float = 1.0, sleep=time.sleep) -> list[ProbeResult]:
    today = datetime.now(timezone.utc).date().isoformat()
    out: list[ProbeResult] = []
    for domain, eps in ENDPOINTS.items():
        for ep in eps:
            out.append(probe_url(domain, ep, since, today, open_fn=open_fn))
            sleep(pause_s)
    return out


def to_markdown(results: list[ProbeResult], run_at: str) -> str:
    L = [f"# Network probe — {run_at}", "",
         "| domain | endpoint | status | kind | blocked by | content-type | redirects | parses | error |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r.domain} | {r.name}{'' if r.endpoint_confirmed_by_docs else ' (unconfirmed)'} | {r.status or '—'} | "
                 f"{r.kind} | {r.blocked_by} | {r.content_type or '—'} | {len(r.redirects)} | "
                 f"{'—' if r.parses_as_expected is None else r.parses_as_expected} | {(r.error or '').replace('|', '/')[:90]} |")
    return "\n".join(L) + "\n"


def results_to_json(results: list[ProbeResult]) -> list[dict]:
    return [asdict(r) for r in results]
