"""Route assessed records into opportunity pipelines and rank WITHIN each pipeline.

There is deliberately no universal score: each pipeline has its own ranking profile, and every
point awarded is explained. Routing never promotes unverified content into a buyer pipeline.
"""

from __future__ import annotations

from typing import Iterable

from . import registry
from .models import Assessment, Opportunity, RawRecord

HARD_NOISE = {"seo_or_content_marketing", "lead_aggregator_or_bot_post", "lead_marketplace_advertising",
              "crypto_bounty_or_token_payment", "spam_campaign"}
BUY_INTENTS = {"explicit_hire_request", "recommendation_request", "quote_request"}
TARGET = {"UK", "UAE", "Europe"}


def route(rec: RawRecord, a: Assessment) -> tuple[str, str]:
    fam = registry.policy(rec.source_key)["family"]
    intent, rel, eng = a.buying_intent.value, a.technical_relevance.value, a.engagement_type.value
    hard = HARD_NOISE & set(a.noise_flags)
    if rec.verification == "fixture":
        return "EXCLUDED", "test fixture"
    if hard:
        return "EXCLUDED", f"noise: {', '.join(sorted(hard))}"
    if intent == "seller_offer":
        return "EXCLUDED", "seller/vendor advertising its own services (not demand)"
    if intent == "job_seeker":
        return "EXCLUDED", "freelancer or job seeker looking for work (not a buyer)"
    if "no_external_invitation" in a.noise_flags and intent in ("none_or_discussion", "problem_only"):
        return "EXCLUDED", "internal project task or discussion: no invitation for outside help"
    if a.freshness.value == "closed":
        return "EXCLUDED", "closed/resolved at source"
    if a.freshness.value == "old":
        return "EXCLUDED", "older than 90 days"
    if rec.verification == "search_snippet_only":
        return "H_RESEARCH_UNVERIFIED", "search snippet only: content not opened/verified"
    if rec.source_key in ("contracts_finder", "find_a_tender", "ted"):
        if rel in ("relevant",):
            return "E_PROCUREMENT", "procurement of Solvant-relevant services (not a direct SME lead)"
        if rel == "uncertain":
            return "H_RESEARCH_UNVERIFIED", "procurement with uncertain service relevance: human review"
        return "EXCLUDED", f"procurement not relevant to Solvant ({rel})"
    if rel == "not_relevant" and intent not in ("employment_or_staffing",):
        return "EXCLUDED", "deliverable is not software/AI/automation/integration work"
    if rel == "product_only":
        return "H_RESEARCH_UNVERIFIED", "licence/product purchase: reseller territory, not an implementation project"
    if intent == "employment_or_staffing" or eng in ("permanent_employment", "staff_augmentation"):
        return ("F_RECRUITMENT_SIGNAL", "employment/staffing: market signal, not consultancy demand") if rel != "not_relevant" \
            else ("EXCLUDED", "unrelated employment advert")
    if fam == "lead_marketplace" or rec.verification == "licensed_import":
        return "G_LICENSED_LEADS", "lead obtained from a lead marketplace / licensed feed"
    strong = intent in BUY_INTENTS or intent == "partner_search" or (fam == "freelance_marketplace" and intent != "none_or_discussion")
    market = a.location.value
    if strong and market == "other":
        return "GLOBAL_REVIEW", f"strong request but outside target markets ({'; '.join(a.location.evidence)})"
    if intent == "partner_search":
        return "C_AGENCY_PARTNER", "explicit outsourcing / white-label / delivery-partner request"
    if fam == "freelance_marketplace" and intent != "none_or_discussion":
        return "B_FREELANCE_PROJECT", f"project posted on {registry.policy(rec.source_key)['name']}"
    if intent in BUY_INTENTS:
        # A business asking for a freelancer/agency OUTSIDE a marketplace is a direct buyer (engagement type recorded separately).
        if rec.verification not in ("api_verified", "reviewer_verified"):
            return "A_DIRECT_SME", "explicit request (user-supplied: verify before outreach)"
        return "A_DIRECT_SME", "explicit request for external implementation help"
    if intent == "paid_bounty":
        return "B_FREELANCE_PROJECT", "paid bounty (fiat) for a defined deliverable"
    if intent == "problem_only" and rel == "relevant":
        return "D_OPERATIONAL_PAIN", "specific operational problem, no request to hire"
    return "H_RESEARCH_UNVERIFIED", f"no buying intent established ({intent}); kept for research"


# ----------------------------------------------------------------------------- ranking profiles
def _pts(cond: bool, n: int, label: str, expl: list[str]) -> int:
    if cond:
        expl.append(f"+{n} {label}")
        return n
    return 0


def rank(rec: RawRecord, a: Assessment, pipeline: str) -> tuple[int, list[str]]:
    e: list[str] = []
    i, rel, biz = a.buying_intent.value, a.technical_relevance.value, a.business_type.value
    fresh, conf, cp = a.freshness.value, a.evidence_confidence.value, a.contact_permission.value
    verified = conf == "verified_source_content"
    s = 0
    if pipeline == "A_DIRECT_SME":
        s += _pts(i == "explicit_hire_request", 30, "explicit request to hire", e)
        s += _pts(i in ("quote_request", "recommendation_request"), 25, f"{i}", e)
        s += _pts(rel == "relevant", 25, "technical relevance confirmed", e)
        s += _pts(biz == "independent_sme_self_reported", 15, "self-reported SME/founder business", e)
        s += _pts(biz == "unknown" or biz == "open_source_or_unknown", 4, "business type unknown", e)
        s += _pts(a.decision_maker_access.value == "self_reported_decision_maker", 10, "poster self-reports a decision role", e)
        s += _pts(fresh == "fresh", 10, "≤30 days old", e) or _pts(fresh == "stale", 4, "31–90 days old", e)
        s += _pts(cp in ("reply_in_thread_invited", "in_platform_only", "per_platform_rules"), 10, "permitted contact route", e)
        s += _pts(verified, 10, "source content verified", e)
        s -= 10 if a.location.value == "unknown" else 0
        if a.location.value == "unknown":
            e.append("-10 location unknown")
    elif pipeline == "B_FREELANCE_PROJECT":
        s += _pts(i in ("explicit_hire_request", "quote_request", "paid_bounty"), 25, "real project request", e)
        s += _pts(rel == "relevant", 25, "scope matches Solvant services", e)
        s += _pts(a.commercial_potential.value == "budget_stated", 10, "budget stated", e)
        rules = registry.marketplace_rules(rec.source_key)
        s += _pts(rules.get("agency_accounts") is True, 10, "agency accounts allowed on platform", e)
        s += _pts(fresh == "fresh", 10, "fresh", e)
        s += _pts(verified, 10, "verified", e)
    elif pipeline == "C_AGENCY_PARTNER":
        s += _pts(True, 30, "explicit outsourcing/partner demand", e)
        s += _pts(rel == "relevant", 25, "services Solvant can deliver", e)
        s += _pts(any("recurring" in x for x in a.commercial_potential.evidence), 15, "recurring potential stated", e)
        s += _pts(cp in ("reply_in_thread_invited", "per_platform_rules", "in_platform_only"), 10, "collaboration route", e)
        s += _pts(fresh == "fresh", 10, "fresh", e)
        s += _pts(verified, 10, "verified", e)
    elif pipeline == "D_OPERATIONAL_PAIN":
        s += _pts(rel == "relevant", 25, "automatable problem", e)
        s += min(30, 10 * len(a.technical_relevance.evidence)); e.append("+ problem specificity")
        s += _pts(biz == "independent_sme_self_reported", 15, "SME", e)
        s += _pts(fresh == "fresh", 10, "fresh", e)
        s += _pts(verified, 10, "verified", e)
    elif pipeline == "E_PROCUREMENT":
        s += _pts(rel == "relevant", 35, "relevant services", e)
        s += _pts(fresh == "fresh", 15, "recent notice", e)
        s += _pts(verified, 10, "verified", e)
        s -= 10 if "formal_bid_required" in a.delivery_complexity.evidence else 0
    elif pipeline in ("F_RECRUITMENT_SIGNAL", "G_LICENSED_LEADS", "GLOBAL_REVIEW", "H_RESEARCH_UNVERIFIED"):
        s += _pts(rel == "relevant", 30, "relevant", e)
        s += _pts(i in BUY_INTENTS | {"partner_search"}, 20, "buying intent", e)
        s += _pts(fresh == "fresh", 10, "fresh", e)
        s += _pts(verified, 10, "verified", e)
    return max(0, min(100, s)), e


NEXT_ACTION = {
    "A_DIRECT_SME": "Open the original post, confirm it is current and the poster can buy; reply only via the permitted route",
    "B_FREELANCE_PROJECT": "Check platform eligibility (agency accounts, fees); propose inside the platform only",
    "C_AGENCY_PARTNER": "Confirm partner terms; reply via the permitted route with a partnership offer",
    "D_OPERATIONAL_PAIN": "Nurture/research: do not pitch unless the community allows it",
    "E_PROCUREMENT": "Read the notice: procedure, eligibility, lots, deadline; bid via the portal or find a prime partner",
    "F_RECRUITMENT_SIGNAL": "Market intelligence only; do not treat as consultancy demand",
    "G_LICENSED_LEADS": "Respond per the lead-marketplace terms; record acquisition cost",
    "H_RESEARCH_UNVERIFIED": "Verify content, date and intent before any use",
    "GLOBAL_REVIEW": "Strong request outside target markets: owner decides",
    "EXCLUDED": "None",
}


def build(rec: RawRecord, a: Assessment) -> Opportunity:
    p, why = route(rec, a)
    score, expl = rank(rec, a, p) if p != "EXCLUDED" else (0, [])
    return Opportunity(record=rec, assessment=a, pipeline=p, pipeline_reason=why, rank_score=score,
                       rank_explanation=expl, next_action=NEXT_ACTION[p])


def mark_spam_campaigns(records: Iterable[RawRecord], min_owners: int = 3) -> set[str]:
    """Same normalised title posted under >= min_owners different repository owners/sources = spam campaign."""
    import re
    groups: dict[str, set[str]] = {}
    ids: dict[str, list[str]] = {}
    for r in records:
        key = re.sub(r"[^a-z0-9]+", " ", r.title.lower()).strip()[:90]
        owner = r.meta.get("repo_owner") or r.author_ref or r.source_id
        groups.setdefault(key, set()).add(owner)
        ids.setdefault(key, []).append(r.source_id)
    return {sid for k, owners in groups.items() if len(owners) >= min_owners for sid in ids[k]}
