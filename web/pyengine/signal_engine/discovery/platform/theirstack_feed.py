"""TheirStack Jobs API (licensed job-postings provider) — employment signals from SMALL companies whose hiring need could be
met by outsourced delivery (automation, AI, integrations, CRM, data/admin work).

Kept strictly separate from customers and marketplace projects: every result is kind "employment" and lands in the
recruitment pipeline (F). Records whose role is contract/freelance/part-time at a small company are flagged
`outsourcing_fit` so sales can offer a delivered project instead of a hire.

COST CONTROL: TheirStack charges 1 credit per job returned; the free plan has 200 credits/month. This feed hard-caps each
run (default 6 jobs → ≤186/month at one run per day) and never pages beyond the cap. The API key is injected by the
session's network proxy (Authorization: Bearer) for api.theirstack.com; without it the feed reports "not configured".

  python -m signal_engine.discovery.platform.theirstack_feed --days 7 --max-credits 6 [--out out/agent/theirstack-YYYYMMDD.json]

Field names follow TheirStack's public API reference; missing fields are tolerated and the first live run is checked.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Optional

API = "https://api.theirstack.com/v1/jobs/search"
HARD_MAX_CREDITS = 8
COUNTRIES = ["GB", "IE", "AE", "DE", "FR", "NL", "BE", "ES", "PT", "IT", "CH", "AT", "DK", "SE", "NO", "FI", "PL", "LU"]
TITLES = ["automation", "n8n", "zapier", "make.com", "ai engineer", "ai developer", "integration", "crm", "hubspot", "salesforce admin",
          "no-code", "low-code", "rpa", "operations automation", "chatbot", "data entry automation"]
CONTRACTISH = re.compile(r"\b(contract|contractor|freelance|freelancer|part[- ]time|temporary|interim|fixed[- ]term|project[- ]based|consultant)\b", re.I)


class NotConfigured(RuntimeError):
    pass


def build_query(days: int, limit: int) -> dict:
    return {"page": 0, "limit": int(limit), "posted_at_max_age_days": int(days), "job_country_code_or": COUNTRIES,
            "job_title_or": TITLES, "company_employee_count_max": 50, "include_total_results": False, "blur_company_data": False,
            "order_by": [{"desc": True, "field": "date_posted"}]}


def fetch(days: int = 7, max_credits: int = 6) -> list[dict]:
    limit = max(1, min(HARD_MAX_CREDITS, int(max_credits)))
    req = urllib.request.Request(API, data=json.dumps(build_query(days, limit)).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "Authorization": "Bearer proxy-injected", "User-Agent": "SolvantDiscovery/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return (json.load(r) or {}).get("data") or []
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 402, 403):
            raise NotConfigured(f"TheirStack API key missing, unauthorised or out of credits (HTTP {exc.code})") from None
        raise


def to_candidate(j: dict) -> Optional[dict]:
    url = j.get("url") or j.get("final_url") or j.get("source_url")
    title = j.get("job_title") or ""
    if not url or not str(url).startswith("https://") or not title:
        return None
    co = j.get("company_object") or {}
    emp = co.get("employee_count")
    desc = (j.get("description") or "")[:600]
    contractish = bool(CONTRACTISH.search(f"{title} {desc} {j.get('employment_statuses') or ''}"))
    small = isinstance(emp, int) and emp <= 50
    return {
        "url": url, "title": title[:300], "evidence_quote": desc, "published_at": (j.get("date_posted") or "")[:10] or None,
        "page_read": False, "query": "theirstack: small-company automation/AI/admin roles", "kind": "employment",
        "source_api": "theirstack", "source_id": str(j.get("id") or url),
        "budget": j.get("salary_string") or None,
        "business": {"name": j.get("company") or co.get("name"), "type": "independent_sme" if small else "unknown",
                     "size": f"{emp} employees" if emp else None, "country": j.get("country") or co.get("country"),
                     "industry": co.get("industry"), "website": (f"https://{co['domain']}" if co.get("domain") else None)},
        "qualification": {"intent": "employment_or_staffing", "relevance": "relevant", "score": 55 if (contractish and small) else 35,
                          "reason": ("small company hiring contract/part-time help for automation work: outsourcing fit" if contractish and small
                                     else "small company hiring for automation/AI/admin work (employment signal)"),
                          "service": "Offer delivered automation project instead of a hire"},
        "facts": {"outsourcing_fit": contractish and small, "remote": j.get("remote"), "location": j.get("short_location") or j.get("location")},
    }


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 7
    cap = int(argv[argv.index("--max-credits") + 1]) if "--max-credits" in argv else 6
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    try:
        jobs = fetch(days, cap)
    except NotConfigured as exc:
        print(f"theirstack feed: NOT CONFIGURED ({exc}). See docs/platform/account-activation.md")
        return 0
    cands = [c for c in (to_candidate(j) for j in jobs) if c]
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w") as fh:
            json.dump(cands, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"theirstack_jobs": len(jobs), "candidates": len(cands), "credits_used_max": min(HARD_MAX_CREDITS, cap),
                      "outsourcing_fit": sum(1 for c in cands if c["facts"]["outsourcing_fit"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
