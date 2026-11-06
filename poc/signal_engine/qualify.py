"""Commercial qualification → actionable priority queues.

Business rules (2026-11-05):
  * Target markets: UK, UAE and all of Europe (see markets.py). Unknown location → review, never auto-excluded.
  * NO budget minimum or maximum. A stated budget is factual metadata only. Large or complex
    work is flagged (delivery partner / extra resources), never rejected for its size.
  * Excluded: vendors advertising services, irrelevant employment ads, unrelated or physical
    automation, closed or outdated items, explicit evidence of a non-target market, synthetic data.
  * Search-index titles are never verified buyers: they go to UNVERIFIED and are never counted.

Queues:
  PRIORITY_A  verified, recent (≤30 d), explicit external-provider demand (Tier A/B), target market
              confirmed, not closed, permitted contact route.
  PRIORITY_B  verified Tier A/B buying intent with something missing or uncertain
              (location unknown, 31–90 days old, date unknown, availability unknown, contact route unknown).
  PRIORITY_C  verified Tier C: a specific operational problem, no explicit request to hire.
  REVIEW      verified, but SERVICE RELEVANCE is uncertain (e.g. IT tender whose deliverable is unclear,
              non-English text not understood reliably). A person decides; never auto-promoted.
  WATCHLIST   verified Tier D: general interest / weak inference / partner-channel posts.
  EXCLUDED    see above.
  UNVERIFIED  search-index titles or anything whose content was not seen.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import sources
from .classify import Classification, _parse_dt, locate
from .models import Signal

RECENT_DAYS = 30
OUTDATED_DAYS = 90
_FX = {"£": 1.0, "GBP": 1.0, "$": 0.78, "USD": 0.78, "€": 0.85, "EUR": 0.85, "AED": 0.21, "CHF": 0.88,
       "NOK": 0.072, "SEK": 0.073, "DKK": 0.114, "PLN": 0.19, "CZK": 0.034}  # rough, informational only
_CUR = r"£|\$|€|\b(?:GBP|USD|EUR|AED|CHF|NOK|SEK|DKK|PLN|CZK)\b"
_MONEY = re.compile(rf"(?P<cur>{_CUR})\s?(?P<amt>\d[\d,.]*\d|\d)\s?(?P<k>[kKmM]\b)?"
                    rf"|(?P<amt2>\d[\d,.]*\d|\d)\s?(?P<k2>[kKmM]\b)?\s?(?P<cur2>{_CUR})")
_HOURLY = re.compile(r"/\s?(?:hr|hour|h)\b|\bper\s+(?:hour|day)\b|\bhourly\b|\bday\s+rate\b", re.I)

PRIORITY_A, PRIORITY_B, PRIORITY_C = "PRIORITY_A", "PRIORITY_B", "PRIORITY_C"
REVIEW, WATCHLIST, EXCLUDED, UNVERIFIED = "REVIEW", "WATCHLIST", "EXCLUDED", "UNVERIFIED"
QUEUE_ORDER = (PRIORITY_A, PRIORITY_B, PRIORITY_C, REVIEW, WATCHLIST, EXCLUDED, UNVERIFIED)

TENDER_PROCESS_NOTE = ("formal tender: confirm procedure, eligibility, lots and submission route before treating it as a sales lead "
                       "(a published notice is not an immediately contactable buyer)")
_PRE_PROCUREMENT = re.compile(r"\bprior\s+information\b|\bmarket\s+(?:engagement|consultation|sounding)\b|\bconsultazione\s+preliminare\b|"
                              r"\bmarktconsultatie\b|\bmarkterkundung\b|\brequest\s+for\s+information\b|\brfi\b|\binformationsfr(?:å|a)gor\b|"
                              r"\bpin\b", re.I)
_AWARD = re.compile(r"\bcontract\s+award\b|\baward\s+notice\b|\bmodification\s+notice\b|\bgegenstand\s+der\s+vergabe\s+war\b|"
                    r"\bwas\s+awarded\b|\bvoluntary\s+ex[\s-]ante\b", re.I)


def procurement_stage(sig: Signal, now: datetime) -> str:
    """Stage of a tender from the notice type / tags / text. Never assumes 'open'."""
    meta = sig.raw_meta or {}
    nt = str(meta.get("notice_type") or "").lower()
    tags = [str(t).lower() for t in (meta.get("tags") or [])]
    text = f"{sig.title}\n{sig.text}"
    if nt.startswith(("can", "veat")) or "award" in tags or "contract" in tags or _AWARD.search(text):
        return "award_or_modification"
    if nt.startswith("pin") or "planning" in tags or _PRE_PROCUREMENT.search(text):
        return "pre_procurement"
    deadline = _parse_dt(sig.deadline_at)
    if deadline is not None:
        return "competition_open" if deadline > now else "competition_closed"
    if nt.startswith("cn") or "tender" in tags:
        return "competition_deadline_unknown"
    return "unknown"

_HARD_REJECT = {
    "vendor_self_promotion": "vendor advertising its own services",
    "recruitment_or_staffing": "employment / staffing advertisement",
    "unrelated_physical_or_industrial_automation": "physical / industrial automation (not Solvant's work)",
    "unrelated_no_automation_scope": "unrelated to automation, AI or integration",
}


@dataclass
class QualRecord:
    url: str
    source: str
    verification_status: str
    title: str
    organisation: str
    country: str
    market: str
    location_evidence: str
    published_at: str
    age_days: Optional[int]
    business_requirement: str
    external_provider_evidence: list[str]
    budget_stated: str                 # verbatim as found, or "not stated"
    budget_kind: str                   # fixed_or_range / rate / notice_value / not_stated
    budget_gbp_estimate: Optional[float]   # rough conversion, informational only
    availability: str                  # verified_open / no_visible_closure / closed / unknown
    availability_basis: str
    contact_route: str
    contact_permitted: Optional[bool]
    source_collection_permitted: bool
    data_use_basis: str
    potential_service: str
    intent_tier: str
    classification_evidence: list[str]
    complexity: str
    delivery_flags: list[str]
    partnership_opportunity: bool
    risk_flags: list[str]
    intent_verified: bool
    service_relevance: str             # relevant / product_only / not_relevant / uncertain
    deliverable_type: str
    relevance_evidence: list[str]      # what shows the deliverable is (not) Solvant's kind of work
    relevance_against: list[str]
    relevance_uncertainty: list[str]
    opportunity_kind: str              # tender_bid / direct_request
    procurement_stage: str             # tenders only; "n/a" otherwise
    delivery_mode: str                 # direct / partner_likely / vendor_or_reseller_only / n/a
    queue: str
    reasons: list[str] = field(default_factory=list)
    missing_details: list[str] = field(default_factory=list)
    score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def parse_budget(text: str) -> tuple[str, Optional[float], str]:
    """Return (verbatim amounts, rough GBP estimate of the largest, kind). Never a fit judgement."""
    found, gbp = [], []
    for m in _MONEY.finditer(text or ""):
        cur = (m.group("cur") or m.group("cur2") or "").upper()
        raw = (m.group("amt") or m.group("amt2") or "")
        k = (m.group("k") or m.group("k2") or "").lower()
        num = raw.replace(",", "")
        if num.count(".") > 1:          # 1.500.000 style thousands separators
            num = num.replace(".", "")
        try:
            v = float(num) * (1000 if k == "k" else 1_000_000 if k == "m" else 1)
        except ValueError:
            continue
        found.append(m.group(0).strip())
        gbp.append(v * _FX.get(cur, 1.0))
    if not found:
        return "not stated", None, "not_stated"
    kind = "rate" if _HOURLY.search(text) else "fixed_or_range"
    return "; ".join(found), max(gbp), kind


def _availability(sig: Signal, now: datetime) -> tuple[str, str]:
    if not sig.is_genuine:
        return "unknown", "page not opened"
    deadline = _parse_dt(sig.deadline_at)
    if deadline is not None:
        return ("verified_open", f"deadline {sig.deadline_at} is in the future") if deadline > now \
            else ("closed", f"deadline {sig.deadline_at} has passed")
    meta = sig.raw_meta or {}
    if meta.get("tender_status") in ("complete", "cancelled", "unsuccessful", "withdrawn"):
        return "closed", f"tender status '{meta['tender_status']}'"
    if meta.get("closed") or meta.get("archived"):
        return "closed", "topic is closed/archived on the forum"
    if meta.get("kind") == "forum_post":
        return "no_visible_closure", "topic still open on the forum; the poster may already have hired (not proof of availability)"
    if meta.get("kind") == "tender" and meta.get("tender_status") == "active":
        return "no_visible_closure", "tender status 'active' but no deadline in the data"
    return "unknown", "no deadline or status in the source"


def qualify(sig: Signal, c: Classification, now: Optional[datetime] = None) -> QualRecord:
    now = now or datetime.now(timezone.utc)
    text = f"{sig.title}\n{sig.text}"
    posted = _parse_dt(sig.posted_at)
    age = (now - posted).days if posted else None
    loc = locate(sig, text) if sig.is_genuine or sig.verification_status == "synthetic" else locate(sig, sig.title)
    is_tender = (sig.raw_meta or {}).get("kind") == "tender"
    stage = procurement_stage(sig, now) if is_tender else "n/a"
    rel = c.relevance or {}
    pol = sources.policy(sig.source)

    budget_str, budget_gbp, budget_kind = parse_budget(text)
    if budget_kind == "not_stated" and sig.value_amount:
        cur = (sig.value_currency or "GBP").upper()
        budget_gbp = sig.value_amount * _FX.get(cur, 1.0)
        budget_str, budget_kind = f"{cur} {sig.value_amount:,.0f} (notice value)", "notice_value"

    avail, avail_basis = _availability(sig, now)
    ext = [e.matched for e in c.evidence if e.group == "external_help"]
    risk = list(c.flags)
    if sig.verification_status == "search_index_only":
        risk.append("title_only_unverified")

    reasons: list[str] = []
    missing: list[str] = []

    if sig.verification_status == "synthetic":
        queue = EXCLUDED
        reasons.append("synthetic test fixture (invalid evidence)")
    elif not sig.is_genuine:
        queue = UNVERIFIED
        reasons.append("source content not seen (search-index title only); never counted as a verified buyer")
    elif c.reject_reason in _HARD_REJECT:
        queue = EXCLUDED
        reasons.append(_HARD_REJECT[c.reject_reason])
    elif c.reject_reason == "unrelated_procurement" or (is_tender and c.service_relevance == "not_relevant"):
        queue = EXCLUDED
        reasons.append(f"procurement unrelated to Solvant's services ({c.deliverable_type})")
    elif is_tender and stage == "award_or_modification":
        queue = EXCLUDED
        reasons.append("award / modification notice: the contract is already placed")
    elif avail == "closed":
        queue = EXCLUDED
        reasons.append(f"closed ({avail_basis})")
    elif age is not None and age > OUTDATED_DAYS:
        queue = EXCLUDED
        reasons.append(f"outdated: {age} days old")
    elif loc.market == "other":
        queue = EXCLUDED
        reasons.append(f"outside target markets ({loc.evidence})")
    elif c.service_relevance == "uncertain":
        queue = REVIEW
        reasons.append("service relevance uncertain: " + "; ".join(rel.get("uncertainty") or ["deliverable unclear"]))
    elif c.service_relevance == "product_only":
        queue = WATCHLIST
        reasons.append("software product / licence purchase with no service scope (vendor or reseller partnership only)")
    elif c.intent_tier in ("A", "B"):
        if is_tender:
            missing.append(TENDER_PROCESS_NOTE)
            if stage == "pre_procurement":
                missing.append("pre-procurement stage (market engagement / prior information): no bid possible yet")
            elif stage != "competition_open":
                missing.append(f"tender stage not confirmed open ({stage})")
        if loc.market == "unknown":
            missing.append("location unknown: review")
        if age is None:
            missing.append("publication date unknown")
        elif age > RECENT_DAYS:
            missing.append(f"not recent ({age} days old)")
        if avail == "unknown":
            missing.append("open/closed status unknown")
        if not pol.contact_permitted:
            missing.append("contact route not confirmed")
        queue = PRIORITY_A if not missing else PRIORITY_B
        reasons.append("verified request for an external provider" + ("" if not missing else " — details missing"))
    elif c.intent_tier == "C":
        queue = PRIORITY_C
        reasons.append("specific operational problem without an explicit request to hire")
        if loc.market == "unknown":
            missing.append("location unknown: review")
    else:
        queue = WATCHLIST
        reasons.append("weak signal (Tier D): general interest, product-only tender or partner channel")

    return QualRecord(
        url=sig.url, source=sig.source, verification_status=sig.verification_status, title=sig.title,
        organisation=sig.organisation or "unknown",
        country=loc.country, market=loc.market, location_evidence=loc.evidence,
        published_at=sig.posted_at or "unknown", age_days=age,
        business_requirement=(sig.text[:400] if sig.text else "unknown (body not retrieved)"),
        external_provider_evidence=ext or ["none found"],
        budget_stated=budget_str, budget_kind=budget_kind, budget_gbp_estimate=budget_gbp,
        availability=avail, availability_basis=avail_basis,
        contact_route=pol.contact_route, contact_permitted=pol.contact_permitted,
        source_collection_permitted=pol.collection_permitted, data_use_basis=pol.basis,
        potential_service=c.suggested_service or "—",
        intent_tier=c.intent_tier,
        classification_evidence=[f"{e.feature}: {e.matched}" for e in c.evidence],
        complexity=c.complexity, delivery_flags=list(c.delivery_flags),
        partnership_opportunity=c.partnership_opportunity, risk_flags=risk,
        intent_verified=sig.is_genuine and c.intent_tier in ("A", "B"),
        service_relevance=c.service_relevance, deliverable_type=c.deliverable_type,
        relevance_evidence=list(rel.get("positive") or []),
        relevance_against=list((rel.get("negative") or []) + (rel.get("traps") or [])),
        relevance_uncertainty=list(rel.get("uncertainty") or []),
        opportunity_kind="tender_bid" if is_tender else "direct_request",
        procurement_stage=stage,
        delivery_mode=("vendor_or_reseller_only" if c.service_relevance == "product_only" else
                       "partner_likely" if c.partnership_opportunity or c.complexity == "high" else
                       "direct" if c.service_relevance == "relevant" else "n/a"),
        queue=queue, reasons=reasons, missing_details=missing, score=c.score,
    )
