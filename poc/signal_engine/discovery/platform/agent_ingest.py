"""Ingest candidates found by the scheduled Claude discovery task (docs/platform/discovery-agent.md).

The Claude session (running on the owner's Claude subscription — no paid AI API) searches the web, qualifies what it finds
and writes a JSON list of candidates. This module is the deterministic gate between that judgement and the database:
  * permitted-method checks: https only; known platforms only; tenders/public procurement, shared AI chats, gig listings,
    job boards and vendor pages rejected; pages of no-fetch platforms can only arrive as search snippets;
  * the existing engine (assess/route/rank) re-classifies every candidate; Claude's qualification is merged as the LLM
    opinion with its reasons kept as evidence, and the engine's noise/exclusion rules always win;
  * snippets are never marked verified (priority capped at B); the human verifies from the dashboard.
Then it pushes to solvant.ingest_records (agent mode). Logs print COUNTS only.

  python -m signal_engine.discovery.platform.agent_ingest candidates.json [--dry-run]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .. import registry
from ..assess import assess
from ..models import Dimension, RawRecord
from ..privacy import clean_text
from ..router import build
from .items import to_item
from .rest import RestError, rpc

ENGINE = "claude-agent+rules-2026.11"

# host suffix -> registry key (order matters: first match wins)
PLATFORMS = [
    ("community.n8n.io", "n8n_community"), ("community.make.com", "make_community"), ("community.zapier.com", "zapier_community"),
    ("powerusers.microsoft.com", "power_platform_community"), ("community.powerplatform.com", "power_platform_community"),
    ("community.hubspot.com", "hubspot_salesforce_pipedrive_zoho_ghl"), ("community.shopify.com", "shopify_woo_xero_qbo_airtable_notion_bubble_webflow_stripe"),
    ("community.airtable.com", "shopify_woo_xero_qbo_airtable_notion_bubble_webflow_stripe"), ("indiehackers.com", "indie_hackers"),
    ("linkedin.com", "linkedin"), ("reddit.com", "reddit"), ("facebook.com", "facebook_groups"), ("instagram.com", "instagram"),
    ("threads.net", "threads"), ("threads.com", "threads"), ("x.com", "x_twitter"), ("twitter.com", "x_twitter"), ("bsky.app", "bluesky"),
    ("github.com", "github_issues"), ("upwork.com", "upwork"), ("freelancer.com", "freelancer_com"), ("freelancer.co.uk", "freelancer_com"),
    ("peopleperhour.com", "peopleperhour"), ("ukbusinessforums.co.uk", "uk_business_forums"),
]
# platforms whose pages the agent may read (public forums / GitHub, low volume, robots.txt permitting)
PAGE_READ_ALLOWED = {"n8n_community", "make_community", "zapier_community", "power_platform_community", "indie_hackers",
                     "hubspot_salesforce_pipedrive_zoho_ghl", "shopify_woo_xero_qbo_airtable_notion_bubble_webflow_stripe",
                     "github_issues", "uk_business_forums"}
REJECT_URL = re.compile(
    r"(find-tender\.service\.gov\.uk|contractsfinder\.service\.gov\.uk|ted\.europa\.eu|\.gov(\.[a-z]{2})?/|sam\.gov|tenders?\b|"
    r"chatgpt\.com/share|chat\.openai\.com/share|claude\.ai/share|g\.co/gemini/share|gemini\.google\.com/share|poe\.com/s/|"
    r"fiverr\.com|upwork\.com/(hire|freelancers|services|resources)/|linkedin\.com/jobs|indeed\.|glassdoor\.|/for-hire|"
    r"\.pages\.dev|\.web\.app)", re.I)
SELLER_TITLE = re.compile(r"^\s*(\[?for hire\]?|i will\b|offering\b|we (build|offer)\b|available for)|"
                          r"\b(developer|designer|expert|freelancer|agency|engineer|consultant)s? (is |are )?available\b|"
                          r"\bopen to (new )?(work|projects|opportunit\w*|roles|clients)\b|\btaking on (new )?(clients|projects)\b|"
                          r"\blooking for (new )?(clients|projects|work)\b", re.I)
INTENTS = {"explicit_hire_request", "recommendation_request", "quote_request", "partner_search", "paid_bounty", "problem_only",
           "employment_or_staffing", "none_or_discussion", "seller_offer", "job_seeker"}
SMALL = {"independent_sme", "startup", "solo_founder", "small_agency"}


class Rejected(ValueError):
    pass


def platform_of(url: str) -> Optional[str]:
    host = (urlsplit(url).hostname or "").lower()
    for suffix, key in PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return key
    return None


def to_record(c: dict) -> RawRecord:
    url = str(c.get("url") or "").strip()
    if not url.startswith("https://"):
        raise Rejected("url must be https")
    if REJECT_URL.search(url):
        raise Rejected("excluded url type (tender/procurement, shared AI chat, gig/job board or vendor page)")
    key = platform_of(url)
    if not key:
        raise Rejected("platform not in the approved list")
    if registry.policy(key)["status"] == "prohibited":
        raise Rejected("source prohibited")
    title = clean_text(str(c.get("title") or ""), limit=300)
    if SELLER_TITLE.search(title):
        raise Rejected("seller/for-hire post")
    quote = clean_text(str(c.get("evidence_quote") or c.get("excerpt") or ""), limit=800)
    if not (title or quote):
        raise Rejected("no title or evidence")
    if "SYNTHETIC" in (title + quote).upper() or ".invalid" in url:
        raise Rejected("synthetic/test data")
    page_read = bool(c.get("page_read")) and key in PAGE_READ_ALLOWED
    biz = c.get("business") or {}
    published = (c.get("published_at") or "").strip() or None
    if published:
        try:
            datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            published = None
    meta = {"kind": "agent_search_result", "discovered_by": "claude_agent", "discovered_via": "claude_web_search",
            "query_category": str(c.get("query") or "")[:120], "platform": key, "page_read": page_read,
            "opportunity_kind": str(c.get("kind") or "")[:30] or None,
            "verification_route": "agent read the original public page" if page_read else "search-engine result only (page not fetched)"}
    if c.get("budget"):
        meta["budget"] = str(c["budget"])[:60]
    return RawRecord(source_key=key, source_id=url, url=url, title=title or quote[:120], body=quote,
                     verification="agent_reviewed" if page_read else "search_snippet_only", created_at=published,
                     state="unknown", fetched_at=datetime.now(timezone.utc).isoformat(), query_id=f"agent:{meta['query_category'][:60]}",
                     organisation=(str(biz.get("name") or "").strip()[:200] or None),
                     country_hint=(str(biz.get("country") or "").strip()[:80] or None), meta=meta)


_GH_ISSUE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(?:issues|discussions)/(\d+)")
TARGET_COUNTRIES = re.compile(
    r"\b(uk|united kingdom|england|scotland|wales|ireland|uae|united arab emirates|dubai|abu dhabi|sharjah|germany|deutschland|"
    r"france|netherlands|belgium|luxembourg|spain|portugal|italy|switzerland|austria|denmark|sweden|norway|finland|iceland|poland|"
    r"czech|slovakia|hungary|romania|bulgaria|greece|croatia|slovenia|serbia|estonia|latvia|lithuania|malta|cyprus|europe|eu)\b", re.I)


def verify_source(rec: RawRecord, fetch=None) -> RawRecord:
    """Re-read the ORIGINAL post through the publisher's official API where one exists (approved Discourse forums, GitHub).
    On success the record carries the source's own title/date/text and verification 'api_verified' — no manual click needed.
    On failure the agent's reading is kept as 'agent_reviewed' with the failure noted; a missing/removed topic is rejected."""
    from . import forum_reader
    fetch = fetch or forum_reader.fetch_topic
    host = (urlsplit(rec.url).hostname or "").lower()
    try:
        if host in forum_reader.FORUM_HOSTS:
            t = fetch(rec.url)
            if t and t.get("title"):
                rec.title, rec.body = clean_text(t["title"], limit=300), clean_text(t.get("text") or rec.body, limit=800)
                rec.created_at = t.get("created") or rec.created_at
                rec.verification = "api_verified"
                rec.meta.update(verification_route="Discourse topic API (original forum)", source_closed=bool(t.get("closed")))
        elif _GH_ISSUE.match(rec.url):
            o, r, n = _GH_ISSUE.match(rec.url).groups()
            import urllib.request
            req = urllib.request.Request(f"https://api.github.com/repos/{o}/{r}/issues/{n}",
                                         headers={"Accept": "application/vnd.github+json", "User-Agent": "SolvantDiscovery/1.0"})
            it = json.load(urllib.request.urlopen(req, timeout=20))
            rec.title, rec.body = clean_text(it.get("title") or rec.title, limit=300), clean_text(it.get("body") or rec.body, limit=800)
            rec.created_at = it.get("created_at") or rec.created_at
            rec.state = it.get("state") or rec.state
            rec.verification = "api_verified"
            rec.meta.update(verification_route="GitHub REST API (original issue)")
    except Exception as exc:   # verification failure never blocks; the lead stays unverified
        code = getattr(exc, "code", None)
        if code in (404, 410):
            raise Rejected("original post no longer exists (removed or hidden)")
        rec.meta["verification_error"] = type(exc).__name__
    return rec


def merge_claude(a, c: dict):
    """Claude's qualification overrides intent/relevance/business type (LLM opinion, reasons kept); noise flags stay."""
    q = c.get("qualification") or {}
    why = clean_text(str(q.get("reason") or ""), limit=300)
    ev = [f"claude: {why}"] if why else ["claude qualification"]
    if q.get("intent") in INTENTS:
        a.buying_intent = Dimension(q["intent"], ev + a.buying_intent.evidence[:2], "medium")
    if q.get("relevance") in ("relevant", "uncertain", "not_relevant", "product_only"):
        a.technical_relevance = Dimension(q["relevance"], ev[:1] + a.technical_relevance.evidence[:3], "medium")
    bt = (c.get("business") or {}).get("type")
    if bt in SMALL:
        a.business_type = Dimension("independent_sme_self_reported", [f"claude: {bt}"], "medium")
    elif bt in ("mid_market", "enterprise"):
        a.business_type = Dimension("larger_organisation", [f"claude: {bt}"], "medium")
    if q.get("decision_maker"):
        a.decision_maker_access = Dimension("self_reported_decision_maker", [f"claude: {q['decision_maker']}"[:120]], "low")
    a.noise_flags = [f for f in a.noise_flags if f != "search_snippet_only"]
    if q.get("service"):
        a.suggested_service = str(q["service"])[:200]
    return a


def _age_days(created: Optional[str], now: datetime) -> Optional[int]:
    if not created:
        return None
    try:
        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))).days


def process(cands: list[dict], now: Optional[datetime] = None, verify: bool = False) -> tuple[list[dict], Counter]:
    now = now or datetime.now(timezone.utc)
    items, rejected, seen = [], Counter(), set()
    for c in cands[:500]:
        try:
            if (c.get("business") or {}).get("type") == "public_sector":
                raise Rejected("public sector / institutional procurement excluded")
            rec = to_record(c)
        except Rejected as exc:
            rejected[str(exc)] += 1
            continue
        if rec.url in seen:
            rejected["duplicate in batch"] += 1
            continue
        seen.add(rec.url)
        if verify:
            try:
                rec = verify_source(rec)
            except Rejected as exc:
                rejected[str(exc)] += 1
                continue
        opp = build(rec, merge_claude(assess(rec, now=now), c))
        it = to_item(opp)
        q = c.get("qualification") or {}
        try:
            score = max(0, min(100, int(q.get("score"))))
            it["rank_score"] = round((it["rank_score"] + score) / 2)
        except (TypeError, ValueError):
            pass
        biz_type = (c.get("business") or {}).get("type")
        # region: Europe/UK/UAE first; explicitly elsewhere ranks lower (never hidden)
        where = " ".join(str(x) for x in ((c.get("business") or {}).get("country"), it.get("country"), it.get("location")) if x)
        if TARGET_COUNTRIES.search(where):
            it["rank_score"] = min(100, it["rank_score"] + 8)
            it["meta"]["region_priority"] = "target market"
        elif where and it.get("location") == "other":
            it["rank_score"] = max(0, it["rank_score"] - 8)
        age = _age_days(rec.created_at, now)
        it["meta"]["age_days"] = age
        if it["pipeline"] != "EXCLUDED":
            # priority follows the blended score; unverified snippets and larger organisations are never top priority
            it["priority"] = "A" if it["rank_score"] >= 70 else "B" if it["rank_score"] >= 45 else "C"
            if it["priority"] == "A" and (rec.verification == "search_snippet_only" or biz_type in ("mid_market", "enterprise")):
                it["priority"] = "B"
            # freshness: the last 7 days lead; 8-30 days at most B; older (or undated) at most C
            if age is None or age > 30:
                it["priority"] = "C" if it["priority"] in ("A", "B") else it["priority"]
            elif age > 7 and it["priority"] == "A":
                it["priority"] = "B"
        it["org_type"] = biz_type or it.get("org_type")
        it["engine_version"] = ENGINE
        it["engine"] = "llm"
        it["meta"]["claude"] = {k: q.get(k) for k in ("intent", "relevance", "score", "reason", "decision_maker", "service") if q.get(k) is not None}
        it["meta"]["business"] = {k: v for k, v in (c.get("business") or {}).items() if k in ("name", "type", "size", "country", "industry", "website")}
        items.append(it)
    return items, rejected


def push(items: list[dict], counts: Counter) -> dict:
    token = os.environ.get("SIGNAL_INGEST_TOKEN", "")   # empty -> the database reads the proxy-injected x-signal-token header
    logs = [{"source_key": k, "status": "ok", "requests": 0, "records": n} for k, n in counts.items()]
    run = {"scope": "discovery", "mode": "agent", "external_run_id": os.environ.get("CLAUDE_RUN_ID", "claude-scheduled-task"),
           "started_at": datetime.now(timezone.utc).isoformat(), "logs": logs}
    total = {"added": 0, "updated": 0, "duplicates": 0, "rejected": 0}
    reasons: Counter = Counter()
    for i in range(0, max(1, len(items)), 200):
        res = rpc("ingest_records", {"p_token": token, "p_run": run if i == 0 else {"scope": "discovery", "mode": "agent"},
                                     "p_items": items[i:i + 200]}) or {}
        for k in total:
            total[k] += int(res.get(k, 0))
        reasons.update(res.get("rejected_reasons") or {})
    return {**total, "rejected_reasons": dict(reasons)}


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: agent_ingest.py candidates.json [--dry-run]")
        return 2
    cands: list[dict] = []
    for p in paths:
        data = json.loads(Path(p).read_text())
        cands += data if isinstance(data, list) else data.get("candidates", [])
    items, rejected = process(cands, verify="--no-verify" not in argv)
    by_pipe = Counter(i["pipeline"] for i in items)
    by_src = Counter(i["source_key"] for i in items)
    print(json.dumps({"candidates": len(cands), "accepted": len(items), "rejected_before_db": dict(rejected),
                      "pipelines": dict(by_pipe), "priority": dict(Counter(i["priority"] for i in items))}, indent=1))
    if "--dry-run" in argv:
        return 0
    try:
        res = push(items, by_src)
    except RestError as exc:
        print(f"push FAILED: HTTP {exc.status}")
        return 3
    print("database: " + json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
