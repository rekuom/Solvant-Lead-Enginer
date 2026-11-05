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

from . import markets
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
    ("platform", _rx(r"\bzapier\b|\bmake\.com\b|\bmake\s+(?:expert|professional|pro|scenario)s?\b|\bn8n\b|\bpower\s+automate\b|\bpower\s+platform\b|\blow[\s-]?code\b|\bno[\s-]?code\b")),
    ("ai_development", _rx(r"\bai\s+(?:development|implementation|solutions?|services|integration|assistants?|models?|platform|tools?|use\s+cases?)\b|\bartificial\s+intelligence\b|\bmachine\s+learning\b|\bgenerative\s+ai\b|\bgen\s?ai\b|\bllms?\b|\blarge\s+language\s+models?\b|\bnatural\s+language\s+processing\b|\bcopilot\b")),
    ("document_processing", _rx(r"\bdocument\s+(?:processing|automation|capture|extraction|management)\b|\bdata\s+extraction\b|\bocr\b|\bintelligent\s+document\b|\bidp\b|\bscanning\s+and\s+indexing\b")),
    ("systems_integration", _rx(r"\bsystems?\s+integration\b|\berp\b|\bsoftware\s+integration\b|\bintegration\s+(?:services|platform|layer)\b|\bmiddleware\b|\bipaas\b")),
    ("integration", _rx(r"\bintegrat\w*\b|\bconnect(?:ing)?\s+(?:our|my|the)?\s*\w*\s*(?:crm|systems?|apis?|tools?)\b|\bapi\b|\bwebhooks?\b")),
    ("crm", _rx(r"\bcrm\b|\bhubspot\b|\bsalesforce\b|\bpipedrive\b|\bzoho\b|\bgohighlevel\b|\bghl\b")),
    ("finance_ops", _rx(r"\binvoic\w*\b|\bbookkeeping\b|\bxero\b|\bquickbooks\b|\bsage\b|\breconcil\w*\b|\baccounts?\s+(?:payable|receivable)\b|\baccounting\s+automation\b|\bfinance\s+automation\b|\bexpense\s+management\b|\bpurchase[\s-]to[\s-]pay\b|\bp2p\b")),
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


# ---------------------------------------------------------------------------
# Service suggestions (first match wins). Names only: no price is assumed —
# scope and budget are agreed per opportunity, at any size.
# ---------------------------------------------------------------------------
SERVICES = [
    (_rx(r"\binvoic|\bxero\b|\bquickbooks\b|\bbookkeeping\b|\breconcil|\baccounts?\s+(?:payable|receivable)\b|\bpurchase[\s-]to[\s-]pay\b|\bexpense"),
     "Finance & invoicing automation (accounting system integration, AP/AR workflows)"),
    (_rx(r"\bdocument\s+(?:processing|automation|capture|extraction)|\bdata\s+extraction\b|\bocr\b|\bidp\b|\bintelligent\s+document"),
     "Document processing & data extraction (AI OCR, validation, system-of-record sync)"),
    (_rx(r"\bmigrat\w*\b|\bzapier\b.*\b(?:to|->)\b.*\b(?:make|n8n)\b"),
     "Automation platform migration and hardening (error paths, retries, monitoring)"),
    (_rx(r"\bats\b|\brecruit\w*\s+automation\b|\bcandidate\b"),
     "Recruitment pipeline automation (ATS sync, matching, outreach sequences)"),
    (_rx(r"\bcrm\b|\bhubspot\b|\bsalesforce\b|\bpipedrive\b|\bcopper\b|\bzoho\b|\bghl\b|\bgohighlevel\b|\bdynamics\b"),
     "CRM integration & automation (lead routing, data sync between systems)"),
    (_rx(r"\bai\s+agents?\b|\bagentic\b|\bllms?\b|\bgenerative\s+ai\b|\bartificial\s+intelligence\b|\bmachine\s+learning\b|\bai\s+(?:development|implementation|solutions?|assistants?|models?)\b"),
     "AI development & implementation (agents, assistants, LLM integration)"),
    (_rx(r"\bpower\s+automate\b|\bpower\s+platform\b|\bn8n\b|\bmake\.com\b|\bmake\s+expert\b|\bzapier\b"),
     "Workflow automation build on the client's platform (n8n / Make / Zapier / Power Automate)"),
    (_rx(r"\berp\b|\bsystems?\s+integration\b|\bsoftware\s+integration\b|\bmiddleware\b|\bapi\b"),
     "Systems & software integration (APIs, middleware, ERP connectors)"),
    (_rx(r"\blead\b|\bbooking\b|\bappointment\b"),
     "Lead capture, qualification & booking workflow"),
    (_rx(r"\breport\w*\b|\bdashboard"),
     "Automated reporting pipeline (data pull, transform, scheduled report)"),
    (_rx(r"\bchat\s?bot|\bsupport\b|\binbox\b|\bemail\b|\bsms\b"),
     "AI inbox / customer-message triage assistant"),
    (_rx(r"\brpa\b|\brobotic\s+process\b|\bintelligent\s+automation\b"),
     "RPA / intelligent automation (process discovery, bots, orchestration)"),
]
DEFAULT_SERVICE = "Business process automation (discovery, build, handover)"

# Informational delivery flags. They NEVER exclude a prospect.
LARGE_PROJECT_GBP = 100_000  # at or above: flag that a delivery partner / extra resources may be needed
COMPLEXITY_HIGH = _rx(r"\berp\b|\bsap\b|\boracle\b|\bdynamics\s*365\b|\bmulti[\s-]?(?:system|site|country|entity)\b|"
                      r"\benterprise[\s-]wide\b|\blegacy\b|\bmigration\b|\bmachine\s+learning\b|\bcomputer\s+vision\b|"
                      r"\bai\s+agents?\b|\bagentic\b|\bdata\s+platform\b|\bcentre\s+of\s+excellence\b|\bcenter\s+of\s+excellence\b")
DELIVERY_REQUIREMENTS = [
    ("security_clearance", _rx(r"\bsecurity\s+clearance\b|\bsc\s+clear\w*\b|\bbpss\b|\bnppv\b|\bdv\s+clear\w*\b")),
    ("certification", _rx(r"\biso\s?27001\b|\bcyber\s+essentials\b|\bsoc\s?2\b|\biso\s?9001\b")),
    ("on_site", _rx(r"\bon[\s-]?site\b|\bon\s+premises\b")),
    ("language", _rx(r"\b(?:fluent|native)\s+(?:french|german|spanish|italian|dutch|arabic|polish|portuguese)\b|\bin\s+(?:french|german|spanish|italian|dutch|arabic)\b")),
    ("framework_or_dps", _rx(r"\bframework\s+agreement\b|\bdynamic\s+purchasing\s+system\b|\bg-cloud\b|\bdps\b")),
    ("insurance", _rx(r"\bprofessional\s+indemnity\b|\binsurance\s+cover\b")),
    ("named_platform", _rx(r"\bblue\s?prism\b|\buipath\b|\bautomation\s+anywhere\b|\bservicenow\b|\bsalesforce\b|\bsap\b")),
]
PARTNERSHIP = _rx(r"\bdelivery\s+partner\b|\bimplementation\s+partner\b|\bconsortium\b|\bsub-?contract\w*\b|\bprime\s+contractor\b|\bfor\s+(?:our|my)\s+clients\b|\bwhite[\s-]?label\b")


TIER_BASE = {"A": 80, "B": 62, "C": 42, "D": 18, "REJECT": 0}
TIER_CAP = {"A": 100, "B": 79, "C": 59, "D": 34, "REJECT": 0}

FRESH_DAYS = 30
STALE_DAYS = 90


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
    flags: list[str] = field(default_factory=list)        # informational only, never exclusionary
    country: Optional[str] = None                          # country name or "unknown" / "other:<x>"
    market: str = "unknown"                                # UK / UAE / Europe / other / unknown
    location_evidence: str = "unknown"
    complexity: str = "unknown"                            # low / medium / high
    delivery_flags: list[str] = field(default_factory=list)
    partnership_opportunity: bool = False

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
    rates = {"GBP": 1.0, "USD": 0.78, "EUR": 0.85, "AED": 0.21, "CHF": 0.88, "NOK": 0.072, "SEK": 0.073, "DKK": 0.114,
             "PLN": 0.19, "CZK": 0.034}  # rough, for informational size banding only
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

    # --- location (place evidence only; never currency) ------------------------
    loc = locate(sig, text)

    # --- informational delivery assessment (never exclusionary) -----------------
    flags: list[str] = []
    gbp = _gbp(sig.value_amount, sig.value_currency)
    delivery = [name for name, rx in DELIVERY_REQUIREMENTS if rx.search(text)]
    if is_tender:
        delivery.append("formal_bid_required")
    high = COMPLEXITY_HIGH.search(text)
    if high or (gbp is not None and gbp >= LARGE_PROJECT_GBP):
        complexity = "high"
    elif len(hits["scope"]) >= 3 or is_tender:
        complexity = "medium"
    elif hits["scope"]:
        complexity = "low"
    else:
        complexity = "unknown"
    partnership = bool(PARTNERSHIP.search(text)) or (gbp is not None and gbp >= LARGE_PROJECT_GBP) \
        or "framework_or_dps" in delivery or (product_tender and tier != "REJECT")
    if gbp is not None and gbp >= LARGE_PROJECT_GBP:
        flags.append("large_project_may_need_delivery_partner")
    if product_tender and tier != "REJECT":
        flags.append("product_procurement_implementation_partner_possible")
    if loc.market == "unknown":
        flags.append("location_unknown_review")
    elif loc.market == "other":
        flags.append("outside_target_markets")
    flags += [f"location_{f}" for f in loc.flags]

    # --- service --------------------------------------------------------------
    service = None
    if tier in ("A", "B", "C"):
        service = DEFAULT_SERVICE
        for rx, name in SERVICES:
            if rx.search(text):
                service = name
                break

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

    return Classification(
        intent_tier=tier,
        actionable=actionable,
        score=int(score),
        freshness=fresh,
        reasons=reasons,
        evidence=evidence,
        reject_reason=reject_reason,
        suggested_service=service,
        flags=flags,
        country=loc.country,
        market=loc.market,
        location_evidence=loc.evidence,
        complexity=complexity,
        delivery_flags=delivery,
        partnership_opportunity=partnership,
    )


def locate(sig: Signal, text: Optional[str] = None) -> "markets.Location":
    """Structured country code from the source first, then the source's own country hint, then text."""
    code = (sig.raw_meta or {}).get("buyer_country_code")
    if code:
        return markets.from_code(code, "buyer country code on the notice")
    if sig.country_hint:
        loc = markets.from_code(sig.country_hint, "source jurisdiction")
        if loc.market != "other":
            return loc
    return markets.detect(text if text is not None else f"{sig.title}\n{sig.text}")
