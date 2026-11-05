"""EU Tenders Electronic Daily (TED) — Search API v3 collector.

POST https://api.ted.europa.eu/v3/notices/search  (anonymous; reuse permitted with credit)
Body: {"query": <expert query>, "fields": [...], "limit": N, "page": n}

Field names and query syntax come from TED's docs and community guides and are NOT yet
confirmed against a live response. The collector therefore:
  * tries the full field list, and on HTTP 400 retries once with a minimal field list;
  * parses every field defensively (multilingual dicts, lists or strings);
  * records the API's error text in the fetch log, so the first live run shows what to fix.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..models import Signal
from ..textutil import make_excerpt, normalise_ws
from .http import FetchBlocked, PoliteClient, classify_error

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
NOTICE_URL = "https://ted.europa.eu/en/notice/-/detail/{pub}"

FULL_FIELDS = ["publication-number", "notice-title", "publication-date", "buyer-name", "buyer-country",
               "notice-type", "deadline-receipt-tender-date-lot", "description-lot", "classification-cpv"]
MINIMAL_FIELDS = ["publication-number", "notice-title", "publication-date", "buyer-name", "buyer-country"]

KEYWORDS = ('"workflow automation"', '"process automation"', '"robotic process automation"', '"artificial intelligence"',
            '"AI solution"', '"chatbot"', '"document processing"', '"data extraction"', '"CRM"', '"system integration"',
            '"Power Automate"', '"low-code"', '"intelligent automation"', '"machine learning"')


def build_query(since_yyyymmdd: str, keywords: Iterable[str] = KEYWORDS) -> str:
    ft = " OR ".join(f"FT~{k}" for k in keywords)
    return f"publication-date>={since_yyyymmdd} AND ({ft})"


def _pick_lang(v: Any) -> str:
    """TED multilingual values: {"eng": "..."} or {"eng": ["..."]}, lists, or plain strings."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return _pick_lang(v[0]) if v else ""
    if isinstance(v, dict):
        for k in ("eng", "ENG", "en", "EN"):
            if k in v:
                return _pick_lang(v[k])
        return _pick_lang(next(iter(v.values()))) if v else ""
    return str(v)


def _first(v: Any) -> Optional[str]:
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v) if v else None


def _iso_date(v: Any) -> Optional[str]:
    s = _first(v)
    if not s:
        return None
    s = s.strip()
    # Accept "2026-10-20", "2026-10-20+02:00", "2026-10-20T00:00:00Z", "20261020"
    try:
        if len(s) == 8 and s.isdigit():
            return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
        core = s[:10]
        datetime.strptime(core, "%Y-%m-%d")
        return f"{core}T00:00:00+00:00" if len(s) <= 16 else s
    except ValueError:
        return None


def parse_notice(n: dict[str, Any], collected_at: Optional[str] = None) -> Optional[Signal]:
    pub = _first(n.get("publication-number"))
    if not pub:
        return None
    title = normalise_ws(_pick_lang(n.get("notice-title")))
    desc = _pick_lang(n.get("description-lot"))
    countries = n.get("buyer-country")
    country = _first(countries)
    return Signal(
        source="ted", source_id=pub, url=NOTICE_URL.format(pub=pub),
        title=title or f"TED notice {pub}", text=make_excerpt(desc),
        verification_status="verified_api",
        posted_at=_iso_date(n.get("publication-date")),
        collected_at=collected_at or datetime.now(timezone.utc).isoformat(),
        deadline_at=_iso_date(n.get("deadline-receipt-tender-date-lot")),
        organisation=normalise_ws(_pick_lang(n.get("buyer-name"))) or None,  # public body
        country_hint=None,
        raw_meta={"kind": "tender", "buyer_country_code": country, "notice_type": _first(n.get("notice-type")),
                  "cpv": n.get("classification-cpv")},
    )


def _post(url: str, body: dict, ua: str, timeout: float, opener=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"User-Agent": ua, "Content-Type": "application/json", "Accept": "application/json"})
    op = opener or (lambda r, t: urllib.request.urlopen(r, timeout=t))
    with op(req, timeout) as resp:
        return json.loads(resp.read())


def fetch_ted(client: PoliteClient, since: datetime, limit: int = 50, max_pages: int = 2,
              log: Optional[list] = None, opener=None) -> list[Signal]:
    """`since` is a datetime; returns at most limit*max_pages notices."""
    log = log if log is not None else []
    query = build_query(since.strftime("%Y%m%d"))
    out: list[Signal] = []
    fields = FULL_FIELDS
    page = 1
    while page <= max_pages:
        body = {"query": query, "fields": fields, "limit": limit, "page": page}
        try:
            client._sleep(max(0.0, client.min_interval_s))  # politeness between POSTs
            res = _post(SEARCH_URL, body, client.user_agent, 30, opener=opener)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            log.append({"source": "ted", "page": page, "status": exc.code, "fields": "full" if fields is FULL_FIELDS else "minimal",
                        "error": detail})
            if exc.code == 400 and fields is FULL_FIELDS:
                fields = MINIMAL_FIELDS  # retry once with minimal fields
                continue
            kind, status = classify_error(exc)
            raise FetchBlocked(f"api.ted.europa.eu: {kind}: HTTP {exc.code} {detail[:200]}", kind, status) from exc
        except Exception as exc:
            kind, status = classify_error(exc)
            raise FetchBlocked(f"api.ted.europa.eu: {kind}: {exc}", kind, status) from exc
        notices = res.get("notices") or res.get("results") or []
        log.append({"source": "ted", "page": page, "status": 200, "returned": len(notices),
                    "total": res.get("totalNoticeCount"), "fields": "full" if fields is FULL_FIELDS else "minimal",
                    "sample_keys": sorted(notices[0].keys())[:20] if notices else []})
        for n in notices:
            s = parse_notice(n)
            if s:
                out.append(s)
        if len(notices) < limit:
            break
        page += 1
    return out
