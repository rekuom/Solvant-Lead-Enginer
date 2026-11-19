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
    ("freelancer.de", "freelancer_com"), ("freelancer.fr", "freelancer_com"), ("freelancer.es", "freelancer_com"),
    ("freelancer.nl", "freelancer_com"), ("freelancer.it", "freelancer_com"), ("freelancer.ae", "freelancer_com"),
    ("peopleperhour.com", "peopleperhour"), ("ukbusinessforums.co.uk", "uk_business_forums"),
    ("malt.co.uk", "malt"), ("malt.fr", "malt"), ("malt.de", "malt"), ("malt.es", "malt"), ("malt.nl", "malt"), ("malt.be", "malt"),
    ("malt.com", "malt"),
    # European freelance project boards (search-only)
    ("freelancermap.de", "eu_freelance_boards"), ("freelancermap.at", "eu_freelance_boards"), ("freelancermap.ch", "eu_freelance_boards"),
    ("freelance.de", "eu_freelance_boards"), ("gulp.de", "eu_freelance_boards"), ("twago.de", "eu_freelance_boards"),
    ("twago.com", "eu_freelance_boards"), ("codeur.com", "eu_freelance_boards"), ("404works.com", "eu_freelance_boards"),
    ("freelance-info.fr", "eu_freelance_boards"), ("workana.com", "eu_freelance_boards"), ("planetfreelance.nl", "eu_freelance_boards"),
    # broader business communities (search-only)
    ("accountingweb.co.uk", "accounting_communities"), ("central.xero.com", "accounting_communities"),
    ("quickbooks.intuit.com", "accounting_communities"), ("community.sage.com", "accounting_communities"),
    ("property118.com", "property_communities"), ("landlordzone.co.uk", "property_communities"), ("propertytribes.com", "property_communities"),
    ("sellercentral.amazon.co.uk", "ecommerce_seller_communities"), ("sellercentral.amazon.com", "ecommerce_seller_communities"),
    ("sellercentral.amazon.de", "ecommerce_seller_communities"), ("sellercentral-europe.amazon.com", "ecommerce_seller_communities"),
    ("community.ebay.co.uk", "ecommerce_seller_communities"), ("community.ebay.com", "ecommerce_seller_communities"),
    ("community.etsy.com", "ecommerce_seller_communities"), ("wordpress.org", "ecommerce_seller_communities"),
    ("support.bigcommerce.com", "ecommerce_seller_communities"),
    ("community.squareup.com", "hospitality_retail_communities"), ("community.lightspeedhq.com", "hospitality_retail_communities"),
    ("community.toasttab.com", "hospitality_retail_communities"),
    ("recruitmentjuice.com", "recruitment_communities"), ("community.bullhorn.com", "recruitment_communities"),
    ("startups.co.uk", "professional_services_communities"), ("community.clio.com", "professional_services_communities"),
    ("gruenderszene.de", "eu_business_communities"), ("deutsche-startups.de", "eu_business_communities"),
    ("forum.wer-weiss-was.de", "eu_business_communities"), ("forum.hardware.fr", "eu_business_communities"),
    ("forocoches.com", "eu_business_communities"), ("forum.frandroid.com", "eu_business_communities"),
]
# official/licensed APIs whose candidates arrive from a feed module (not from a page the agent read)
API_SOURCES = {"freelancer": "freelancer_com", "theirstack": "theirstack"}
# platforms whose pages the agent may read (public forums / GitHub, low volume, robots.txt permitting)
PAGE_READ_ALLOWED = {"n8n_community", "make_community", "zapier_community", "power_platform_community", "indie_hackers",
                     "hubspot_salesforce_pipedrive_zoho_ghl", "shopify_woo_xero_qbo_airtable_notion_bubble_webflow_stripe",
                     "github_issues", "uk_business_forums", "eu_freelance_boards", "peopleperhour"}
# never acceptable, whatever the route
REJECT_ALWAYS = re.compile(
    r"(find-tender\.service\.gov\.uk|contractsfinder\.service\.gov\.uk|ted\.europa\.eu|\.gov(\.[a-z]{2})?/|sam\.gov|tenders?\b|"
    r"chatgpt\.com/share|chat\.openai\.com/share|claude\.ai/share|g\.co/gemini/share|gemini\.google\.com/share|poe\.com/s/)", re.I)
# not acceptable from agent web search (job boards etc. are only accepted through a licensed job-data API)
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
URGENT = re.compile(r"\b(urgent(ly)?|asap|as soon as possible|immediately|right away|this week|by (monday|tuesday|wednesday|thursday|friday|"
                    r"tomorrow|end of (the )?(week|month))|deadline|time[- ]sensitive|quick turnaround|dringend|sofort|urgente?|"
                    r"au plus vite|rapidement|lo antes posible|met spoed|zo snel mogelijk|al più presto)\b", re.I)
_AMOUNT = re.compile(r"(\d[\d,.]*)\s*(k)?\b", re.I)
# rough FX to GBP for ranking only (never shown as a converted price)
FX = {"GBP": 1.0, "£": 1.0, "EUR": 0.85, "€": 0.85, "USD": 0.78, "$": 0.78, "AED": 0.21, "CHF": 0.9, "AUD": 0.5, "CAD": 0.57,
      "INR": 0.0093, "SEK": 0.073, "NOK": 0.072, "DKK": 0.11, "PLN": 0.2}
DEFAULT_INTENT = {"marketplace": "explicit_hire_request", "employment": "employment_or_staffing", "partner": "partner_search"}


def budget_gbp(text: Optional[str]) -> Optional[float]:
    """Largest amount in a budget string, roughly in GBP (ranking only). Hourly rates are scaled to a ~20-hour engagement."""
    if not text:
        return None
    t = str(text)
    rate = next((v for k, v in FX.items() if k in t.upper() or k in t), 0.78)
    vals = []
    for num, k in _AMOUNT.findall(t):
        try:
            v = float(num.replace(",", "")) * (1000 if k else 1)
        except ValueError:
            continue
        vals.append(v)
    if not vals:
        return None
    v = max(vals) * rate
    if re.search(r"hour|/h\b|per h|hourly", t, re.I):
        v *= 20
    return round(v, 2)


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
    api = c.get("source_api") if c.get("source_api") in API_SOURCES else None
    if api == "freelancer" and platform_of(url) != "freelancer_com":
        api = None                       # a Freelancer API candidate must point at freelancer.com
    if REJECT_ALWAYS.search(url) or (not api and REJECT_URL.search(url)):
        raise Rejected("excluded url type (tender/procurement, shared AI chat, gig/job board or vendor page)")
    key = API_SOURCES[api] if api else platform_of(url)
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
    page_read = bool(c.get("page_read")) and (key in PAGE_READ_ALLOWED or api is not None)
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
    if api:
        meta.update(source_api=api, api_id=str(c.get("source_id") or "")[:40] or None,
                    verification_route={"freelancer": "Freelancer.com official API", "theirstack": "TheirStack licensed job-data API"}[api])
        meta["discovered_via"] = f"{api}_api"
        if isinstance(c.get("facts"), dict):
            meta["facts"] = {k: v for k, v in c["facts"].items() if k in ("skills", "bid_count", "upgrades", "outsourcing_fit", "remote", "location")}
    if c.get("board_listing") and page_read:
        meta.update(board_listing=True, verification_route="read from the public project board")
        if isinstance(c.get("facts"), dict):
            meta["facts"] = {k: v for k, v in c["facts"].items() if k in ("bid_count", "end_customer", "contract", "remote", "language", "replies")}
    if c.get("budget"):
        meta["budget"] = str(c["budget"])[:60]
    verification = ("licensed_import" if api == "theirstack" else "api_verified" if api == "freelancer"
                    else "agent_reviewed" if page_read else "search_snippet_only")
    return RawRecord(source_key=key, source_id=url, url=url, title=title or quote[:120], body=quote,
                     verification=verification, created_at=published,
                     state="unknown", fetched_at=datetime.now(timezone.utc).isoformat(), query_id=f"agent:{meta['query_category'][:60]}",
                     organisation=(str(biz.get("name") or "").strip()[:200] or None),
                     country_hint=(str(biz.get("country") or "").strip()[:80] or None), meta=meta)


_GH_ISSUE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(?:issues|discussions)/(\d+)")
TARGET_COUNTRIES = re.compile(
    r"\b(uk|united kingdom|england|scotland|wales|ireland|uae|united arab emirates|dubai|abu dhabi|sharjah|germany|deutschland|"
    r"france|netherlands|belgium|luxembourg|spain|portugal|italy|switzerland|austria|denmark|sweden|norway|finland|iceland|poland|"
    r"czech|slovakia|hungary|romania|bulgaria|greece|croatia|slovenia|serbia|estonia|latvia|lithuania|malta|cyprus|europe|eu)\b", re.I)


def verify_source(rec: RawRecord, fetch=None, fetch_freelancer=None, fetch_board=None) -> RawRecord:
    """Re-read the ORIGINAL post through the publisher's official API where one exists (approved Discourse forums, GitHub).
    On success the record carries the source's own title/date/text and verification 'api_verified' — no manual click needed.
    On failure the agent's reading is kept as 'agent_reviewed' with the failure noted; a missing/removed topic is rejected."""
    from . import boards_reader, forum_reader
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
        elif host in boards_reader.BOARD_HOSTS and rec.meta.get("board_listing"):
            t = (fetch_board or boards_reader.fetch_listing)(rec.url)
            if t is None:
                raise Rejected("original post no longer exists (removed or hidden)")
            if t.get("closed"):
                rec.state = "closed"
                rec.meta["source_closed"] = True
            rec.meta.update(verification_route="listing re-read automatically from the public board")
        elif rec.source_key == "freelancer_com" and str(rec.meta.get("api_id") or "").isdigit():
            from . import freelancer_feed
            p = (fetch_freelancer or freelancer_feed.get_project)(int(rec.meta["api_id"]))
            if not p:
                raise Rejected("original post no longer exists (removed or hidden)")
            if p.get("status") not in (None, "active", "open"):
                rec.state = "closed"
                rec.meta["source_closed"] = True
            rec.verification = "api_verified"
            rec.meta.update(verification_route="Freelancer.com official API (project re-checked)")
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
    except Rejected:
        raise
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
    intent = q.get("intent") if q.get("intent") in INTENTS else None
    kind = str(c.get("kind") or "")
    if kind == "employment" and intent not in ("employment_or_staffing", None):
        intent = "employment_or_staffing"          # employment signals never masquerade as customer demand
    if intent is None and kind in DEFAULT_INTENT and a.buying_intent.value in ("none_or_discussion", "problem_only", "unknown"):
        intent, ev = DEFAULT_INTENT[kind], [f"{kind} listing: posted request" if kind != "employment" else "job advert"]
    if intent:
        a.buying_intent = Dimension(intent, ev + a.buying_intent.evidence[:2], "medium")
    if q.get("relevance") in ("relevant", "uncertain", "not_relevant", "product_only"):
        a.technical_relevance = Dimension(q["relevance"], ev[:1] + a.technical_relevance.evidence[:3], "medium")
    elif c.get("board_listing") and a.technical_relevance.value in ("not_relevant", "uncertain", "unknown"):
        # the board reader's multilingual service filter matched (the rule engine's relevance terms are English-only)
        from .boards_reader import STRONG
        m = STRONG.search(f"{c.get('title') or ''} {(c.get('evidence_quote') or '')[:500]}")
        if m:
            a.technical_relevance = Dimension("relevant", [f"board listing: '{m.group(0)}'"], "medium")
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
        # urgency and realistic commercial value (ranking only; nothing is invented)
        text = f"{rec.title} {rec.body}"
        if URGENT.search(text):
            it["rank_score"] = min(100, it["rank_score"] + 6)
            it["meta"]["urgency"] = URGENT.search(text).group(0)[:40]
        value = budget_gbp(c.get("budget"))
        if value is not None:
            it["meta"]["value_gbp_est"] = value
            adj = 10 if value >= 5000 else 6 if value >= 1000 else -20 if value < 100 else -8 if value < 300 else 0
            it["rank_score"] = max(0, min(100, it["rank_score"] + adj))
        bids = ((c.get("facts") or {}).get("bid_count"))
        if isinstance(bids, int) and bids >= 50:
            it["rank_score"] = max(0, it["rank_score"] - 5)      # crowded marketplace project: lower realistic win chance
            it["meta"]["crowded"] = bids
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


def search_entries(searches: list[dict]) -> list[dict]:
    """Normalise the task's search log: {strategy, query, lang?, market?, results?, kept?}. Text only, no lead content."""
    out = []
    for x in searches[:200]:
        strategy, query = str(x.get("strategy") or "").strip().lower()[:40], clean_text(str(x.get("query") or ""), limit=300)
        if strategy and query:
            out.append({"strategy": strategy, "query": query, "lang": str(x.get("lang") or "")[:10] or None,
                        "market": str(x.get("market") or "")[:20] or None, "kept": max(0, min(100, int(x.get("kept") or 0)))})
    return out


def log_searches(searches: list[dict]) -> dict:
    return rpc("log_searches", {"p_token": os.environ.get("SIGNAL_INGEST_TOKEN", ""), "p_searches": search_entries(searches)}) or {}


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
    searches: list[dict] = []
    for p in paths:
        data = json.loads(Path(p).read_text())
        cands += data if isinstance(data, list) else data.get("candidates", [])
        if isinstance(data, dict):
            searches += [x for x in data.get("searches", []) if isinstance(x, dict)]
    items, rejected = process(cands, verify="--no-verify" not in argv)
    by_pipe = Counter(i["pipeline"] for i in items)
    by_src = Counter(i["source_key"] for i in items)
    print(json.dumps({"candidates": len(cands), "searches_logged": len(search_entries(searches)), "accepted": len(items), "rejected_before_db": dict(rejected),
                      "pipelines": dict(by_pipe), "priority": dict(Counter(i["priority"] for i in items))}, indent=1))
    if "--dry-run" in argv:
        return 0
    try:
        res = push(items, by_src)
    except RestError as exc:
        print(f"push FAILED: HTTP {exc.status}")
        return 3
    print("database: " + json.dumps(res))
    if searches:
        try:
            print("search log: " + json.dumps(log_searches(searches)))
        except RestError as exc:
            print(f"search log FAILED: HTTP {exc.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
