"""Conservative, explainable buying-intent classifier.

Design principles (see docs/intent-scoring.md):
  * Every tier must be justified by text that actually appears in the source.
    Each matched rule records the exact matched phrase as evidence.
  * Hard negatives (vendor self-promotion, recruitment, physical/industrial
    automation) are checked BEFORE positive intent, so "hiring" or "automation"
    alone can never produce a high tier.
  * Content-based intent tier and the actionable (outreach) decision are kept
    separate: a strong post that is stale, closed or unverified is not actionable.

This is a deterministic baseline. Phase 2 adds an LLM classifier that must cite
spans from the source; this module remains as a guard-rail and regression check.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .models import Signal

TIERS = ("A", "B", "C", "D", "REJECT")

# ---------------------------------------------------------------------------
# Patterns. Each entry: (feature_name, compiled regex). Order within a list is
# irrelevant; all matches are recorded as evidence.
# ---------------------------------------------------------------------------
_W = r"(?:[\w./&+-]+\s+){0,4}"  # up to 4 filler words, e.g. "a no-code automation"
_PROVIDER = (
    r"(?:expert|freelancer|consultant|consultancy|agency|developer|dev|specialist|builder|"
    r"professional|pro|someone|somebody|person|company|firm|partner|automator|integrator)s?"
)


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


VENDOR = [
    ("for_hire_tag", _rx(r"\[\s*for\s+hire\s*\]|^\s*for\s+hire\b")),
    ("i_will_offer", _rx(r"\bi\s+will\s+(?:build|create|automate|set\s+up|design|develop)\b")),
    ("seeking_work", _rx(r"\b(?:looking\s+for|seeking|open\s+to)\s+(?:new\s+)?(?:remote\s+)?(?:opportunities|work|clients|roles|gigs)\b")),
    ("available_for_hire", _rx(r"\bavailable\s+for\s+(?:hire|work|new\s+projects)\b")),
    ("offering_services", _rx(r"\b(?:we|i)\s+offer\b|\bmy\s+services\b|\bbook\s+a\s+(?:free\s+)?(?:call|consultation)\s+with\s+(?:me|us)\b")),
]

RECRUITMENT = [
    ("employment_terms", _rx(r"\bfull[\s-]?time\b|\bsalary\b|\bjob\s+offer\b|\bpermanent\s+(?:role|position)\b|\bjoin\s+our\s+team\b|\bbenefits\s+package\b|\bplus\s+commission\b|\bcommission\b")),
    ("job_title_hiring", _rx(r"\bhiring\b[\s:!-]*(?:[\w&/+.-]+\s+){0,5}(?:engineer|specialist|manager|executive|analyst|associate|assistant|intern)s?\b")),
    ("staff_augmentation", _rx(r"\bongoing\s+contractor\s+work\b|\bpart[\s-]?time\b|\bhourly\s+support\b")),
]

PARTNER = [
    ("for_our_clients", _rx(r"\bfor\s+(?:our|my)\s+clients\b|\bagency\s+work\b|\bwhite[\s-]?label\b")),
    ("collaboration", _rx(r"\bopen\s+collaboration\b|\bpartnership\b|\bspecialists\s+welcome\b")),
]

# Physical / industrial automation and other "automation" that Solvant does not sell.
OFF_TOPIC = [
    ("physical_automation", _rx(r"\bquadruped\b|\brobot(?!ics?\s+process)(?:s|ics)?\b|\bautonomous\b|\btool\s+room\b|\bmachin(?:e|ery)\b|\bplc\b|\bconveyor\b|\bsample\s+collection\b|\bwarehouse\s+automation\b|\bbuilding\s+automation\b|\bhome\s+automation\b")),
]

EXTERNAL_HELP = [
    ("looking_for_provider", _rx(rf"\blooking\s+(?:for|to\s+hire|to\s+work\s+with)\s+(?:a\s+|an\s+)?{_W}{_PROVIDER}\b")),
    ("recommend_provider", _rx(rf"\bcan\s+(?:anyone|someone|you)\s+recommend\b|\brecommendations?\s+for\s+(?:a\s+|an\s+)?{_W}{_PROVIDER}\b")),
    ("hire_provider", _rx(rf"\b(?:hire|hiring)\s+(?:a\s+|an\s+)?{_W}(?:expert|freelancer|consultant|developer|builder|pro|agency|professional)s?\b")),
    ("provider_needed", _rx(r"\b(?:pro|expert|developer|freelancer|consultant|builder|help)\s+needed\b")),
    ("seeking_provider", _rx(rf"\bseeking\s+(?:a\s+|an\s+)?{_W}(?:expert|builder|developer|freelancer|consultant|partner|agency)s?\b")),
    ("need_someone_to_build", _rx(r"\bneed\s+(?:someone|somebody|an?\s+(?:expert|freelancer|developer|consultant))\s+to\b|\bneed\s+help\s+(?:to\s+|with\s+)?(?:connect|connecting|automat\w*|build|building|set(?:ting)?\s+up|integrat\w*)\b")),
    ("pay_for_work", _rx(r"\bfor\s+a\s+fee\b|\bpaid\s+(?:project|work|gig|task|engagement)\b|\bwilling\s+to\s+pay\b|\bsend\s+(?:me\s+|us\s+)?a\s+quote\b|\bneed\s+a\s+quote\b")),
    ("expert_for_project", _rx(rf"\b{_PROVIDER}\s+for\s+(?:an?\s+)?{_W}project\b")),
]

SCOPE = [
    ("automation", _rx(r"\bautomat\w*\b")),
    ("workflow", _rx(r"\bworkflows?\b")),
    ("platform", _rx(r"\bzapier\b|\bmake\.com\b|\bmake\s+(?:expert|professional|pro|scenario)s?\b|\bn8n\b|\bpower\s+automate\b|\blow[\s-]?code\b|\bno[\s-]?code\b")),
    ("integration", _rx(r"\bintegrat\w*\b|\bconnect(?:ing)?\s+(?:our|my|the)?\s*\w*\s*(?:crm|systems?|apis?|tools?)\b|\bapi\b|\bwebhooks?\b")),
    ("crm", _rx(r"\bcrm\b|\bhubspot\b|\bsalesforce\b|\bpipedrive\b|\bzoho\b|\bgohighlevel\b|\bghl\b")),
    ("finance_ops", _rx(r"\binvoic\w*\b|\bbookkeeping\b|\bxero\b|\bquickbooks\b|\bsage\b|\breconcil\w*\b")),
    ("reporting", _rx(r"\breporting\b|\breports?\b|\bdashboards?\b")),
    ("ai_agent", _rx(r"\bai\s+agents?\b|\bchat\s?bots?\b|\brpa\b|\brobotic\s+process\b|\bintelligent\s+automation\b|\bopenai\b|\bllm\b")),
    ("data_ops", _rx(r"\bspreadsheets?\b|\bdata\s+entry\b|\bexcel\b|\bgoogle\s+sheets\b")),
    ("lead_ops", _rx(r"\blead\s+(?:management|capture|gen\w*|routing)\b|\bbooking\b|\bonboarding\b|\boutreach\b")),
]

BUDGET_OR_PROJECT = [
    ("money_amount", _rx(r"[£$€]\s?\d[\d,]*(?:\.\d+)?\s?k?\b|\b\d[\d,]*\s?(?:gbp|usd|aed|eur)\b")),
    ("budget_word", _rx(r"\bbudget\b|\bfixed[\s-]?price\b|\bfor\s+a\s+fee\b|\bpaid\s+project\b")),
    ("timeline", _rx(r"\b\d+\s*[-–]\s*\d+\s*(?:days|weeks)\b|\bdeadline\b|\bby\s+end\s+of\s+(?:the\s+)?(?:month|week)\b")),
    ("defined_project", _rx(r"\bproject\b(?!s)|\bto\s+build\s+(?:a|an|our|my)\b|\bbuild\s+(?:a|an)\s+\w+")),
]

# Freelance / one-off wording overrides job-title recruitment wording.
FREELANCE_ENGAGEMENT = _rx(r"\bfreelance\b|\bone[\s-]?off\b|\bfixed[\s-]?price\b|\bcontract\s+project\b")

# Tenders buying a product/licence rather than implementation services.
PRODUCT_PROCUREMENT = _rx(r"\bplatform\b|\btool\b|\bsoftware\b|\blicen[cs]es?\b|\bsubscription\b")
SERVICE_PROCUREMENT = _rx(r"\bservices?\b|\bimplement\w*\b|\bpartner\b|\bdelivery\b|\bconsultan\w*\b|\bdevelopment\b")

# Generic AI interest (weak; Tier D at most).
AI_INTEREST = _rx(r"\bai\b|\bartificial\s+intelligence\b|\bmachine\s+learning\b|\bchatgpt\b|\bgenai\b")

ONGOING = _rx(r"\bongoing\b|\blong[\s-]?term\b|\bretainer\b|\bper\s+month\b|/mo\b")

PROBLEM = [
    ("manual_work", _rx(r"\bmanual(?:ly)?\b|\bcopy(?:ing)?\s+and\s+past\w*\b|\bcopy(?:ing)?\s+(?:\w+\s+){0,2}(?:from|into)\b|\bdata\s+entry\b|\bre-?typ\w*\b")),
    ("time_cost", _rx(r"\b(?:spends?|spending|wast\w*|takes?)\s+(?:us\s+|me\s+)?(?:hours|days|\d+\s+hours)\b|\btime[\s-]consuming\b")),
    ("pain", _rx(r"\bstruggl\w*\b|\bnightmare\b|\bbottleneck\b|\bfrustrat\w*\b|\bdrowning\b|\bmess\b")),
]

GEO = {
    "UK": _rx(r"\b(?:uk|u\.k\.|united\s+kingdom|england|scotland|wales|northern\s+ireland|london|manchester|birmingham|leeds|glasgow|edinburgh|bristol|liverpool)\b|£"),
    "UAE": _rx(r"\b(?:uae|u\.a\.e\.|dubai|abu\s+dhabi|sharjah|ajman|emirates)\b|\baed\b"),
}

# ---------------------------------------------------------------------------
# Service suggestions (first match wins). Price ranges are Solvant's standard
# packages, not inferred from the source.
# ---------------------------------------------------------------------------
SERVICES = [
    (_rx(r"\binvoic|\bxero\b|\bquickbooks\b|\bbookkeeping\b|\breconcil"),
     "Invoice & payment-reminder automation (accounting system + email)", "£1,200–£2,000"),
    (_rx(r"\bmigrat\w*\b|\bzapier\b.*\b(?:to|->)\b.*\b(?:make|n8n)\b"),
     "Automation platform migration and hardening (error paths, retries, monitoring)", "£1,000–£2,500"),
    (_rx(r"\bats\b|\brecruit\w*\s+automation\b|\bcandidate\b"),
     "Recruitment pipeline automation (ATS sync, matching, outreach sequences)", "£1,500–£3,000"),
    (_rx(r"\bcrm\b|\bhubspot\b|\bsalesforce\b|\bpipedrive\b|\bcopper\b|\bzoho\b|\bghl\b|\bgohighlevel\b"),
     "CRM integration & lead routing between existing systems", "£1,500–£3,000"),
    (_rx(r"\blead\b|\bbooking\b|\bappointment\b"),
     "Lead capture, qualification & booking workflow", "£1,200–£2,500"),
    (_rx(r"\breport\w*\b|\bdashboard"),
     "Automated reporting pipeline (data pull, transform, scheduled report)", "£1,000–£2,500"),
    (_rx(r"\bchat\s?bot|\bsupport\b|\binbox\b|\bemail\b|\bsms\b"),
     "AI inbox / customer-message triage assistant", "£1,500–£3,000"),
    (_rx(r"\bdocument|\bpdf\b|\bocr\b|\bdata\s+entry\b"),
     "Document extraction into your system of record (AI OCR + validation)", "£1,500–£3,000"),
    (_rx(r"\brpa\b|\brobotic\s+process\b|\bintelligent\s+automation\b"),
     "RPA / intelligent-automation pilot for one process", "£2,000–£3,000 (pilot only)"),
]
DEFAULT_SERVICE = ("Automation discovery sprint + first production workflow", "£1,000–£1,500")

TIER_BASE = {"A": 80, "B": 62, "C": 42, "D": 18, "REJECT": 0}
TIER_CAP = {"A": 100, "B": 79, "C": 59, "D": 34, "REJECT": 0}

FRESH_DAYS = 30
STALE_DAYS = 90
TICKET_CEILING_GBP = 3000
TICKET_STRETCH_GBP = 10000  # above this, Solvant can only bid a pilot / sub-lot


@dataclass
class Evidence:
    feature: str
    group: str
    matched: str


@dataclass
class Classification:
    intent_tier: str
    actionable: str              # A-D, REJECT, HOLD_VERIFY, TEST_ONLY
    score: int
    freshness: str               # fresh / stale / outdated / closed / unknown
    reasons: list[str]
    evidence: list[Evidence] = field(default_factory=list)
    reject_reason: Optional[str] = None
    suggested_service: Optional[str] = None
    suggested_price: Optional[str] = None
    fit_flags: list[str] = field(default_factory=list)
    country: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _scan(groups: dict[str, list[tuple[str, re.Pattern[str]]]], text: str) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = {}
    for gname, rules in groups.items():
        hits = []
        for fname, rx in rules:
            m = rx.search(text)
            if m:
                hits.append(Evidence(fname, gname, m.group(0).strip()))
        out[gname] = hits
    return out


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def freshness_of(sig: Signal, now: datetime) -> str:
    deadline = _parse_dt(sig.deadline_at)
    if deadline is not None and deadline < now:
        return "closed"
    posted = _parse_dt(sig.posted_at)
    if posted is None:
        return "unknown"
    age = (now - posted).days
    if age <= FRESH_DAYS:
        return "fresh"
    if age <= STALE_DAYS:
        return "stale"
    return "outdated"


def _gbp(amount: Optional[float], currency: Optional[str]) -> Optional[float]:
    if amount is None:
        return None
    rates = {"GBP": 1.0, "USD": 0.78, "EUR": 0.85, "AED": 0.21}  # rough, for fit banding only
    return amount * rates.get((currency or "GBP").upper(), 1.0)


def _downgrade(tier: str) -> str:
    return {"A": "B", "B": "C", "C": "D", "D": "D", "REJECT": "REJECT"}[tier]


def classify(sig: Signal, now: Optional[datetime] = None) -> Classification:
    now = now or datetime.now(timezone.utc)
    text = f"{sig.title}\n{sig.text}"
    hits = _scan(
        {
            "vendor": VENDOR,
            "recruitment": RECRUITMENT,
            "partner": PARTNER,
            "off_topic": OFF_TOPIC,
            "external_help": EXTERNAL_HELP,
            "scope": SCOPE,
            "budget_or_project": BUDGET_OR_PROJECT,
            "problem": PROBLEM,
        },
        text,
    )
    is_tender = sig.raw_meta.get("kind") == "tender"
    if is_tender:
        hits["external_help"].append(Evidence("public_tender", "external_help", "public procurement notice"))
        hits["budget_or_project"].append(Evidence("tender_project", "budget_or_project", "formal procurement = defined project"))
        if sig.value_amount:
            hits["budget_or_project"].append(
                Evidence("tender_value", "budget_or_project", f"{sig.value_currency or ''} {sig.value_amount:,.0f}".strip())
            )
    ongoing = ONGOING.search(text)
    freelance = FREELANCE_ENGAGEMENT.search(text)
    if freelance and not ongoing:
        # "Hiring: Freelance X Engineer" is buying external help, not employment.
        hits["recruitment"] = [e for e in hits["recruitment"] if e.feature != "job_title_hiring"]
        if not hits["external_help"]:
            hits["external_help"].append(Evidence("freelance_engagement", "external_help", freelance.group(0)))
    product_tender = bool(is_tender and PRODUCT_PROCUREMENT.search(sig.title) and not SERVICE_PROCUREMENT.search(sig.title))
    ai_interest = AI_INTEREST.search(text)
    # Tier A needs to know WHAT will be automated, not just the word "automation".
    specific_scope = any(e.feature != "automation" for e in hits["scope"])

    evidence = [e for g in hits.values() for e in g]
    reasons: list[str] = []
    reject_reason = None
    has = {k: bool(v) for k, v in hits.items()}

    # --- intent tier (content only) -----------------------------------------
    if has["off_topic"]:
        tier, reject_reason = "REJECT", "unrelated_physical_or_industrial_automation"
        reasons.append("Mentions physical/industrial automation, which Solvant does not sell.")
    elif not has["scope"] and not has["problem"] and ai_interest and not has["vendor"] and not has["recruitment"]:
        tier = "D"
        evidence.append(Evidence("ai_interest", "weak", ai_interest.group(0)))
        reasons.append("Mentions AI generally; no automation scope or request — weak inference only.")
    elif not has["scope"] and not has["problem"]:
        tier, reject_reason = "REJECT", "unrelated_no_automation_scope"
        reasons.append("No business-automation scope found in the text.")
    elif has["vendor"]:
        tier, reject_reason = "REJECT", "vendor_self_promotion"
        reasons.append("Author is offering services, not buying them.")
    elif has["recruitment"] and not (has["external_help"] and any(
        e.feature in ("money_amount", "budget_word") for e in hits["budget_or_project"]) and not ongoing):
        tier, reject_reason = "REJECT", "recruitment_or_staffing"
        reasons.append("Reads as employment/staffing (role, salary, part-time or ongoing hours), not a scoped project.")
    elif product_tender:
        tier = "D"
        reasons.append("Tender buys a software product/licence, not implementation services.")
    elif has["partner"]:
        tier = "D"
        reasons.append("Agency/partner sourcing for its own clients: a channel or competitor, not an end buyer.")
    elif has["external_help"] and has["scope"] and has["budget_or_project"] and not ongoing and specific_scope:
        tier = "A"
        reasons.append("Explicitly seeks an external provider for automation work with a defined project or budget.")
    elif has["external_help"] and has["scope"] and has["budget_or_project"] and not ongoing:
        tier = "B"
        reasons.append("Seeks an external provider with a project/budget, but does not say WHAT to automate: capped at B.")
    elif has["external_help"] and has["scope"]:
        tier = "B"
        if ongoing:
            reasons.append("Seeks external automation help but as ongoing capacity, not a defined project.")
        else:
            reasons.append("Actively asks for an external provider to implement automation; no budget/project detail.")
    elif has["problem"] and has["scope"]:
        tier = "C"
        reasons.append("Describes a concrete operational problem automation could solve; no request to hire.")
    elif has["problem"]:
        tier = "D"
        reasons.append("Operational complaint without clear automation scope or request for help.")
    else:
        tier = "D"
        reasons.append("Mentions automation/AI topics only; buying intent is an inference.")

    # --- score ----------------------------------------------------------------
    score = TIER_BASE[tier]
    if tier != "REJECT":
        score += 4 * (len(hits["scope"]) - 1)
        score += 5 * len(hits["budget_or_project"])
        score += 3 * max(0, len(hits["external_help"]) - 1)
        score = max(TIER_BASE[tier], min(TIER_CAP[tier], score))

    # --- fit ------------------------------------------------------------------
    fit: list[str] = []
    country = sig.country_hint
    if not country:
        for c, rx in GEO.items():
            if rx.search(text):
                country = c
                break
    if country not in ("UK", "UAE"):
        fit.append("geography_unconfirmed")
    gbp = _gbp(sig.value_amount, sig.value_currency)
    if gbp is not None:
        if gbp > TICKET_STRETCH_GBP:
            fit.append("value_far_above_ticket_size")
        elif gbp > TICKET_CEILING_GBP:
            fit.append("value_above_ticket_size")

    # --- service --------------------------------------------------------------
    service, price = None, None
    if tier in ("A", "B", "C"):
        service, price = DEFAULT_SERVICE
        for rx, name, p in SERVICES:
            if rx.search(text):
                service, price = name, p
                break
        if "value_far_above_ticket_size" in fit:
            price = f"{price} — tender far exceeds standard packages; bid only as sub-contractor or skip"

    # --- actionable decision ----------------------------------------------------
    fresh = freshness_of(sig, now)
    actionable = tier
    if sig.verification_status == "synthetic":
        actionable = "TEST_ONLY"
        reasons.append("Synthetic test fixture: never a lead.")
    elif tier == "REJECT":
        actionable = "REJECT"
    elif sig.verification_status == "search_index_only":
        actionable = "HOLD_VERIFY"
        reasons.append("Only the search-index title was seen; open the URL and confirm content, date and status before outreach.")
    elif fresh in ("outdated", "closed"):
        actionable, reject_reason = "REJECT", f"{fresh}"
        reasons.append(f"Signal is {fresh}; too late for outreach.")
    elif fresh == "stale":
        actionable = _downgrade(tier)
        reasons.append("Older than 30 days: downgraded one tier.")
    elif fresh == "unknown":
        actionable = "C" if tier in ("A", "B") else tier
        reasons.append("Posting date unknown: capped at Tier C until confirmed.")
    if "value_far_above_ticket_size" in fit and actionable in ("A", "B"):
        actionable = "C"
        reasons.append("Contract value far exceeds Solvant's £1k–£3k packages: capped at Tier C.")

    return Classification(
        intent_tier=tier,
        actionable=actionable,
        score=int(score),
        freshness=fresh,
        reasons=reasons,
        evidence=evidence,
        reject_reason=reject_reason,
        suggested_service=service,
        suggested_price=price,
        fit_flags=fit,
        country=country,
    )
