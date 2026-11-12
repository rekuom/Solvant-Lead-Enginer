"""Flatten an engine Opportunity into the platform item schema. Source facts and interpretation stay separate:
record fields -> source facts; assessment -> `dims` (interpretation with evidence and confidence)."""
from __future__ import annotations

import re
from typing import Optional

from ...textutil import canonical_url, fingerprint
from ..models import Opportunity
from . import ENGINE_VERSION

GENUINE = {"explicit_hire_request", "quote_request", "recommendation_request", "partner_search", "paid_bounty"}
ACTIONABLE = {"A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER", "E_PROCUREMENT", "G_LICENSED_LEADS", "GLOBAL_REVIEW"}
DIMS = ("technical_relevance", "buying_intent", "engagement_type", "business_type", "decision_maker_access", "freshness",
        "delivery_complexity", "evidence_confidence", "commercial_potential", "contact_permission", "location")
TECH = [
    ("AI agents", r"\b(ai|llm) agents?\b|\bagentic\b"), ("LLM / GPT", r"\b(llm|gpt-?\d?|openai|chatgpt|claude|gemini|rag)\b"),
    ("n8n", r"\bn8n\b"), ("Make", r"\bmake\.com\b|\bintegromat\b"), ("Zapier", r"\bzapier\b"),
    ("Power Automate", r"\bpower automate\b|\bpower platform\b"), ("HubSpot", r"\bhubspot\b"), ("Salesforce", r"\bsalesforce\b"),
    ("Pipedrive", r"\bpipedrive\b"), ("Zoho", r"\bzoho\b"), ("GoHighLevel", r"\bgo ?high ?level\b|\bghl\b"),
    ("Shopify", r"\bshopify\b"), ("Xero", r"\bxero\b"), ("QuickBooks", r"\bquickbooks\b"), ("Airtable", r"\bairtable\b"),
    ("Notion", r"\bnotion\b"), ("Python", r"\bpython\b"), ("APIs / integration", r"\bapi\b|\bintegrat\w+|\bwebhooks?\b"),
    ("CRM", r"\bcrm\b"), ("Document processing / OCR", r"\bocr\b|\bdocument (processing|extraction)\b|\binvoice (processing|extraction)\b"),
    ("Data extraction / scraping", r"\bdata extraction\b|\bscrap(e|ing)\b"), ("RPA", r"\brpa\b|\buipath\b"),
    ("Chatbot", r"\bchat ?bots?\b|\bvoice ?bots?\b"), ("Workflow automation", r"\bworkflow automation\b|\bautomat\w+"),
]
_TECH = [(n, re.compile(p, re.I)) for n, p in TECH]


def technologies(text: str) -> list[str]:
    return [n for n, rx in _TECH if rx.search(text or "")][:12]


def priority(o: Opportunity) -> Optional[str]:
    """A = actionable pipeline + genuine request + relevant; B = actionable or relevant; C = everything else kept.
    Low certainty is never treated as irrelevance: uncertain records get C (review), not exclusion."""
    a = o.assessment
    if o.pipeline == "EXCLUDED":
        return None
    if o.pipeline in ACTIONABLE and a.buying_intent.value in GENUINE and a.technical_relevance.value == "relevant":
        return "A"
    if o.pipeline in ACTIONABLE or a.technical_relevance.value == "relevant":
        return "B"
    return "C"


def contact_route(o: Opportunity) -> str:
    v = o.assessment.contact_permission.value
    rules = (o.record.meta or {}).get("marketplace_rules") or {}
    if rules and rules.get("off_platform_contact") is False:
        return "In-platform only (platform rules)"
    return {"reply_in_thread_invited": "Reply in the public thread (invited)", "in_platform_only": "In-platform only",
            "per_platform_rules": "Per platform rules", "procurement_portal": "Via the procurement portal"}.get(v, "Not established: verify first")


def to_item(o: Opportunity, rights_note: Optional[str] = None) -> dict:
    r, a = o.record, o.assessment
    d = a.to_dict()
    dims = {k: d[k] for k in DIMS if k in d}
    pos = [f"{k}: {e}" for k in ("technical_relevance", "buying_intent", "commercial_potential") for e in dims.get(k, {}).get("evidence", [])][:12]
    neg = list(a.noise_flags) + [f"missing: {m}" for m in a.missing_facts][:12]
    meta = {k: v for k, v in (r.meta or {}).items() if k in ("kind", "query_category", "discovered_via", "verification_route", "deadline_at",
                                                              "tender_status", "cpv", "budget", "marketplace_rules", "origin", "notes",
                                                              "verified_by", "landing_source", "licence_allows_export")}
    meta["rank_explanation"] = o.rank_explanation[:10]
    meta["next_action"] = o.next_action
    if r.author_ref:
        meta["author_ref"] = r.author_ref   # salted hash only
    return {
        "canonical_url": canonical_url(r.url), "fingerprint": fingerprint(r.title + " " + r.body), "source_key": r.source_key,
        "source_id": r.source_id, "url": r.url, "title": r.title[:500], "body_excerpt": r.body[:4000],
        "requirement_summary": r.body[:600], "published_at": r.created_at, "source_state": r.state, "verification": r.verification,
        "organisation": r.organisation, "country": r.country_hint, "location": a.location.value, "org_type": a.business_type.value,
        "technologies": technologies(r.title + " " + r.body), "budget_text": (r.meta or {}).get("budget"),
        "pipeline": o.pipeline, "pipeline_reason": o.pipeline_reason, "priority": priority(o), "rank_score": o.rank_score,
        "suggested_service": a.suggested_service, "contact_route": contact_route(o), "dims": dims, "noise_flags": list(a.noise_flags),
        "missing_facts": list(a.missing_facts), "positive_evidence": pos, "negative_evidence": neg, "engine_version": ENGINE_VERSION,
        "query_id": r.query_id, "discovered_via": (r.meta or {}).get("discovered_via"), "meta": meta, "rights_note": rights_note,
        "acquisition_cost": (r.meta or {}).get("acquisition_cost"),
    }
