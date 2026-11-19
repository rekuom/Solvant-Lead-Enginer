"""Freelancer.com projects through the OFFICIAL Freelancer API (developers.freelancer.com), for the daily discovery task.

Permitted use: search active projects with a registered app's OAuth token; proposals stay in-platform (a human bids on
Freelancer.com; off-platform contact is never assumed). The token is injected by the session's network proxy as the
`Freelancer-OAuth-V1` header for www.freelancer.com — this code never sees it. Without it the feed reports "not configured".

  python -m signal_engine.discovery.platform.freelancer_feed --days 7 [--out out/agent/freelancer-YYYYMMDD.json]

Output: candidate objects in the agent_ingest format (kind "marketplace", source_api "freelancer").
API field names follow the public API reference; unknown fields are ignored, and the first live run is checked.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

API = "https://www.freelancer.com/api/projects/0.1"
QUERIES = ["n8n", "make.com", "zapier", "workflow automation", "ai agent", "chatbot", "crm integration", "api integration",
           "hubspot", "xero integration", "shopify automation", "data extraction", "document automation", "airtable", "mvp"]
TARGET_COUNTRIES = {"united kingdom", "ireland", "united arab emirates", "germany", "france", "netherlands", "belgium", "spain",
                    "portugal", "italy", "switzerland", "austria", "denmark", "sweden", "norway", "finland", "poland", "czech republic",
                    "luxembourg", "greece", "romania", "estonia", "latvia", "lithuania", "malta", "cyprus"}
UA = {"User-Agent": "SolvantDiscovery/1.0", "Accept": "application/json"}


class NotConfigured(RuntimeError):
    pass


def _get(path: str, params: list[tuple[str, str]]) -> dict:
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise NotConfigured("Freelancer API token missing or not authorised") from None
        raise


def search(query: str, since_unix: int, limit: int = 50) -> list[dict]:
    params = [("query", query), ("limit", str(limit)), ("compact", "true"), ("full_description", "true"), ("job_details", "true"),
              ("user_details", "true"), ("user_country_details", "true"), ("from_time", str(since_unix)), ("sort_field", "time_updated")]
    d = _get("/projects/active/", params)
    res = d.get("result") or {}
    users = res.get("users") or {}
    out = []
    for p in res.get("projects") or []:
        p = dict(p)
        owner = users.get(str(p.get("owner_id"))) or {}
        p["_owner_country"] = ((owner.get("location") or {}).get("country") or {}).get("name")
        out.append(p)
    return out


def get_project(project_id: int) -> Optional[dict]:
    d = _get(f"/projects/{int(project_id)}/", [("full_description", "true"), ("job_details", "true")])
    return d.get("result") or None


def to_candidate(p: dict, query: str) -> Optional[dict]:
    if p.get("status") not in (None, "active", "open"):
        return None
    seo = p.get("seo_url")
    if not seo or not p.get("id"):
        return None
    ts = p.get("time_submitted") or p.get("submitdate")
    published = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat() if ts else None
    budget = p.get("budget") or {}
    cur = (p.get("currency") or {}).get("code") or ""
    btxt = None
    if budget.get("minimum") or budget.get("maximum"):
        btxt = f"{cur} {budget.get('minimum') or '?'}–{budget.get('maximum') or '?'} ({p.get('type') or 'fixed'})".strip()
    country = p.get("_owner_country")
    desc = (p.get("description") or p.get("preview_description") or "").strip()
    jobs = ", ".join(j.get("name", "") for j in (p.get("jobs") or [])[:6])
    bids = (p.get("bid_stats") or {}).get("bid_count")
    return {
        "url": f"https://www.freelancer.com/projects/{seo}", "title": (p.get("title") or "")[:300],
        "evidence_quote": desc[:600], "published_at": published, "page_read": True, "query": f"freelancer api: {query}",
        "kind": "marketplace", "source_api": "freelancer", "source_id": str(p["id"]), "budget": btxt,
        "business": {"type": "unknown", "country": country},
        "facts": {"skills": jobs, "bid_count": bids, "upgrades": [k for k, v in (p.get("upgrades") or {}).items() if v][:5]},
    }


def in_target_market(c: dict) -> bool:
    """UK/Europe/UAE owners first; an unknown owner country is kept (the gate ranks it), a known other country is dropped
    unless --all-countries is passed (keeps the daily review list focused)."""
    country = ((c.get("business") or {}).get("country") or "").strip().lower()
    return not country or country in TARGET_COUNTRIES


def collect(days: int = 7, queries: Iterable[str] = QUERIES, per_query: int = 50, delay_s: float = 1.0,
            all_countries: bool = False) -> tuple[list[dict], dict]:
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    seen, cands, stats = set(), [], {"requests": 0, "projects": 0, "errors": 0}
    for q in queries:
        try:
            projects = search(q, since, per_query)
            stats["requests"] += 1
        except NotConfigured:
            raise
        except Exception:
            stats["errors"] += 1
            continue
        for p in projects:
            c = to_candidate(p, q)
            if c and not all_countries and not in_target_market(c):
                stats["outside_target"] = stats.get("outside_target", 0) + 1
                continue
            if c and c["source_id"] not in seen:
                seen.add(c["source_id"])
                cands.append(c)
        stats["projects"] = len(cands)
        time.sleep(delay_s)
    return cands, stats


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 7
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    try:
        cands, stats = collect(days, all_countries="--all-countries" in argv)
    except NotConfigured as exc:
        print(f"freelancer feed: NOT CONFIGURED ({exc}). See docs/platform/account-activation.md")
        return 0
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w") as fh:
            json.dump(cands, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"freelancer_projects": len(cands), **stats}))
    if not out:
        print(json.dumps(cands, ensure_ascii=False, indent=1)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
