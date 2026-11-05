"""UK public procurement collectors (Open Contracting Data Standard).

Sources (both free, no key, Open Government Licence v3.0):
  * Contracts Finder  – below/above-threshold notices, England + UK-wide
      GET https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search
  * Find a Tender     – above-threshold notices, all UK
      GET https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages

The parser targets the OCDS 1.1 release schema and is tolerant of missing fields.
The notice-URL mapping below follows the public URL formats observed in search
results (…/Notice/<guid> and …/Notice/<NNNNNN-YYYY>); it must be re-validated on
the first live run because live API access was blocked in the Phase 1 session.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

from ..models import Signal
from ..textutil import make_excerpt, normalise_ws
from .http import PoliteClient

CF_SEARCH = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
FTS_PACKAGES = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"

_GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_FTS_ID_RE = re.compile(r"\b(\d{6}-\d{4})\b")

DEFAULT_KEYWORDS = ("automation", "workflow", "integration", "CRM", "RPA", "low code", "chatbot", "AI",
                    "artificial intelligence", "document processing", "data extraction")


def _first(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v:
            return v
    return None


def cf_notice_url(release: dict[str, Any]) -> Optional[str]:
    for cand in (release.get("ocid", ""), release.get("id", ""), (release.get("tender") or {}).get("id", "")):
        m = _GUID_RE.search(cand or "")
        if m:
            return f"https://www.contractsfinder.service.gov.uk/Notice/{m.group(0).lower()}"
    return None


def fts_notice_url(release: dict[str, Any]) -> Optional[str]:
    for cand in (release.get("id", ""), (release.get("tender") or {}).get("id", ""), release.get("ocid", "")):
        m = _FTS_ID_RE.search(cand or "")
        if m:
            return f"https://www.find-tender.service.gov.uk/Notice/{m.group(1)}"
    return None


def parse_release_package(
    pkg: dict[str, Any],
    source: str,
    verification_status: str = "verified_api",
    collected_at: Optional[str] = None,
) -> list[Signal]:
    url_for = cf_notice_url if source == "contracts_finder" else fts_notice_url
    releases: Iterable[dict[str, Any]] = pkg.get("releases") or []
    out: list[Signal] = []
    collected_at = collected_at or datetime.now(timezone.utc).isoformat()
    for r in releases:
        tender = r.get("tender") or {}
        url = url_for(r)
        if not url:
            continue  # no verifiable evidence URL -> unusable
        status = tender.get("status")
        value = tender.get("value") or {}
        buyer = (r.get("buyer") or {}).get("name")
        if not buyer:
            buyer = next((p.get("name") for p in r.get("parties") or [] if "buyer" in (p.get("roles") or [])), None)
        out.append(
            Signal(
                source=source,
                source_id=r.get("ocid") or r.get("id") or url,
                url=url,
                title=normalise_ws(tender.get("title") or r.get("title") or ""),
                text=make_excerpt(tender.get("description") or ""),
                verification_status=verification_status,
                posted_at=_first(r.get("date"), (tender.get("tenderPeriod") or {}).get("startDate")),
                collected_at=collected_at,
                deadline_at=(tender.get("tenderPeriod") or {}).get("endDate"),
                organisation=buyer,  # public body: publishing its name is the point of the notice
                country_hint="UK",
                value_amount=value.get("amount"),
                value_currency=value.get("currency"),
                raw_meta={"kind": "tender", "tender_status": status, "tags": r.get("tag")},
            )
        )
    return out


def fetch_contracts_finder(
    client: PoliteClient, published_from: str, published_to: str, keywords: Iterable[str] = DEFAULT_KEYWORDS, size: int = 100
) -> list[Signal]:
    signals: list[Signal] = []
    for kw in keywords:
        q = urlencode({"keyword": kw, "publishedFrom": published_from, "publishedTo": published_to,
                       "stages": "tender", "size": size})
        pkg = client.get_json(f"{CF_SEARCH}?{q}", check_robots=False)  # documented public API
        signals += parse_release_package(pkg, "contracts_finder")
    return signals


def fetch_find_a_tender(client: PoliteClient, updated_from: str, limit: int = 100, max_pages: int = 5) -> list[Signal]:
    signals: list[Signal] = []
    url: Optional[str] = f"{FTS_PACKAGES}?{urlencode({'updatedFrom': updated_from, 'stages': 'tender', 'limit': limit})}"
    pages = 0
    while url and pages < max_pages:
        pkg = client.get_json(url, check_robots=False)  # documented public API
        signals += parse_release_package(pkg, "find_a_tender")
        url = (pkg.get("links") or {}).get("next")
        pages += 1
    return signals
