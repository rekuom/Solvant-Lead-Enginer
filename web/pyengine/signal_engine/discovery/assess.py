"""Multidimensional assessment (dimensions A–J) for discovered records.

Each dimension is decided independently from evidence in the RawRecord and the source
policy, and carries the evidence it used. The Phase 1–3 classifier is reused for technical
relevance, intent phrases, vendor/recruitment detection, location and complexity.

Nothing here invents facts: business size, founder status and decision-maker roles are only
ever "self_reported" (stated in the source) or "unknown" — never inferred from a job title.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ..classify import classify, locate
from ..models import Signal
from ..qualify import parse_budget
from . import registry
from .models import Assessment, Dimension, RawRecord, VERIFIED


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


# ----------------------------------------------------------------------------- intent phrases (beyond classify)
RECOMMENDATION = _rx(r"\bcan\s+(?:anyone|someone|you)\s+recommend\b|\b(?:any\s+)?recommendations?\s+for\b|\bwho\s+(?:do\s+you|would\s+you)\s+(?:use|recommend)\b|"
                     r"\bpeut-on\s+me\s+recommander\b|\bkann\s+(?:mir\s+)?jemand\s+(?:einen?|eine)\b.*\bempfehlen\b|\balguien\s+(?:me\s+)?(?:puede\s+)?recomendar\b|"
                     r"\bkan\s+iemand\s+(?:een\s+)?\w*\s*aanbevelen\b|\bqualcuno\s+(?:mi\s+)?(?:può\s+)?consigliare\b")
QUOTE = _rx(r"\brequest\s+for\s+(?:proposals?|quotes?|quotation)\b|\brfp\b|\brfq\b|\b(?:get|send|need|want)\s+(?:a\s+|some\s+)?(?:quotes?|proposals?|estimates?)\b|"
            r"\bdevis\b|\bangebot\s+(?:einholen|anfordern)\b|\bpresupuesto\b|\bofferte\b|\bpreventivo\b")
PARTNER_SEARCH = _rx(r"\bwhite[\s-]?label\w*\b|\bsub-?contract\w*\b|\boutsourc\w+\s+(?:\w+\s+){0,2}(?:development|implementation|automation|work)\b|"
                     r"\b(?:delivery|implementation|technical|development)\s+partner\b|\bfor\s+(?:our|my)\s+clients\b|\boverflow\s+work\b|\bagency\s+partner\b")
JOB_SEEKER = _rx(r"\bopen\s+to\s+(?:work|new\s+roles|opportunities)\b|\b(?:looking|seeking)\s+for\s+(?:a\s+)?(?:job|work|remote\s+(?:work|roles|opportunities))\b|"
                 r"\bavailable\s+for\s+(?:hire|work|freelance)\b|\bhire\s+me\b|\bmy\s+portfolio\b")
SOLICIT = _rx(r"\b(?:looking|searching)\s+(?:for|to\s+hire)\s+(?:a|an|some|someone|somebody)\b|\bwe\s+(?:need|are\s+looking\s+for)\s+(?:a|an|someone)\b|"
              r"\bhire\s+(?:a|an)\s+\w+|\bwe\s+will\s+pay\b|\bwilling\s+to\s+pay\b|\bpaid\s+(?:gig|project|task|opportunity)\s+(?:for|available)\b|"
              r"\bfreelancers?\s+(?:wanted|needed)\b|\bcontractors?\s+(?:wanted|needed)\b|\bopen\s+to\s+(?:proposals|offers|quotes)\b")
PAID_BOUNTY = _rx(r"\bbounty\b|\breward\b|\bprize\b")
INVITATION = _rx(r"\bcontact\s+me\b|\breach\s+out\b|\bemail\s+me\b|\bdm\s+me\b|\bsend\s+(?:me\s+)?(?:your\s+)?(?:proposal|quote|rate|cv|portfolio)\b|\bapply\b|"
                 r"\binterested\?|\bcomment\s+below\b|\blet\s+me\s+know\b|\bget\s+in\s+touch\b|\bpm\s+me\b|\bopen\s+to\s+(?:proposals|offers)\b")

# ----------------------------------------------------------------------------- engagement type
ENGAGEMENT = [
    ("permanent_employment", _rx(r"\bfull[\s-]?time\b|\bpermanent\b|\bsalary\b|\bjob\s+offer\b|\bbenefits\b|\bjoin\s+our\s+team\b|\bequity\s+and\s+salary\b|\bcdi\b|\bfestanstellung\b")),
    ("staff_augmentation", _rx(r"\bongoing\s+(?:contractor|remote)\s+work\b|\bhours?\s+(?:per|a)\s+week\b|\bpart[\s-]?time\b|\bhourly\s+support\b|\bretainer\b|\blong[\s-]?term\s+(?:contract|role)\b")),
    ("partnership", PARTNER_SEARCH),
    ("freelance_project", _rx(r"\bfreelanc\w*\b|\bfixed[\s-]?price\b|\bone[\s-]?off\b|\bgig\b|\bproject\s+budget\b|\bpaid\s+project\b|\bupwork\b|\bfiverr\b|\bpeopleperhour\b|\bmalt\b")),
    ("agency_or_consultancy", _rx(r"\bagenc(?:y|ies)\b|\bconsultan(?:t|cy|ts)\b|\bconsulting\s+firm\b|\bstudio\b|\bdevelopment\s+(?:company|firm|team)\b|\bexternal\s+(?:team|partner|provider)\b")),
    ("contract", _rx(r"\bcontractor\b|\bcontract\s+(?:role|work|position|basis)\b|\bday\s+rate\b|\bb2b\s+contract\b")),
]

# ----------------------------------------------------------------------------- business type (self-reported only)
PUBLIC_SECTOR = _rx(r"\b(?:city|county|borough|district|parish)\s+council\b|\bministry\b|\bmunicipalit\w+\b|\bnhs\b|\bgovernment\b|\bpublic\s+(?:authority|body|sector)\b|"
                    r"\bgemeente\b|\bkommune?\b|\bmairie\b|\bayuntamiento\b|\buniversit\w+\b")
AGENCY = _rx(r"\b(?:our|my|we\s+are\s+an?|we're\s+an?)\s+(?:\w+\s+)?agency\b|\bfor\s+(?:our|my)\s+clients\b|\bwhite[\s-]?label\b")
ENTERPRISE = _rx(r"\benterprise[\s-]wide\b|\bmultinational\b|\bfortune\s+500\b|\bplc\b|\b\d{1,3}(?:,\d{3})+\s+employees\b|\b(?:[5-9]\d\d|\d{4,})\s+employees\b")
SME = _rx(r"\bsmall\s+business\w*\b|\bsmb\b|\bsme\b|\bfamily[\s-](?:run|owned)\b|\bour\s+small\s+team\b|\bteam\s+of\s+\d{1,3}\b|\b\d{1,3}[\s-](?:person|people|employee|staff)\b|"
          r"\bmy\s+(?:shop|store|clinic|practice|salon|restaurant|firm|business|company|startup)\b|\bour\s+(?:shop|store|clinic|practice|salon|restaurant|firm|startup)\b|\bstartup\b|\bstart-up\b|"
          r"\bpetite\s+entreprise\b|\bkleines?\s+unternehmen\b|\bpyme\b|\bmkb\b|\bpmi\b")
HOBBY = _rx(r"\bside\s+project\b|\bhobby\b|\bpersonal\s+project\b|\bfor\s+fun\b|\bmy\s+thesis\b|\bhomework\b|\bschool\s+project\b|\bjust\s+(?:learning|starting\s+out)\b|\bstudent\s+project\b")
EMPLOYEES = _rx(r"\bteam\s+of\s+(\d{1,4})\b|\b(\d{1,4})[\s-](?:person|people|employee|staff)\b")
DECISION_ROLE = _rx(r"\bI(?:'m| am)\s+(?:the\s+|a\s+)?(?:co-?)?(founder|owner|ceo|managing\s+director|director|cto|coo|head\s+of\s+\w+|operations\s+manager)\b|"
                    r"\bas\s+(?:the\s+|a\s+)?(?:co-?)?(founder|owner|ceo|director)\b|\bmy\s+(?:own\s+)?(?:business|company|agency|firm|shop)\b")

# ----------------------------------------------------------------------------- noise / new false-positive categories
SEO_CONTENT = _rx(r"^(?:top|best)\s+\d*|^\d+\s+(?:signs|reasons|ways|tips|mistakes|benefits)\b|\bbest\s+[\w\s]{0,40}\b(?:compan(?:y|ies)|agenc(?:y|ies)|services|tools)\s+(?:in|for)\b|^how\s+(?:to|businesses)\b|"
                  r"\bultimate\s+guide\b|\bstrategy\s+for\b|\bcomplete\s+guide\b|\bstep[\s-]by[\s-]step\s+guide\b|\bpremium\s+workspaces?\b")
LEAD_BOT = _rx(r"\[lead:|\bleads?\s*[—–-]\s*\d{4}|\blead\s+watch\b|\bopportunit(?:y|ies)\s+(?:monitor|board|watch|radar)\b|\[board\]|\bdaily\s+[\w\s]{0,20}leads\b|"
               r"\bjob-to-cash\b|\bpaid\s+work\s+lead\b|\bautonomous\s+[\w\s-]{0,30}(?:revenue|income|cash)\b|\b(?:sales|revenue)\s+recovery\s+[—–-]\s+verified\b|"
               r"海外机会|\bfree-finder-of-lance\b|\bradar\s*:\s*hilos\b|\bhiring\s+lead\s*:|\bnew\s+jobs?\s+found\b|\bjobs?\s+alert\b|"
               r"\balert\s*:\s*\d+\s+new\b|\bscan\s+result\b|\bdigest\b|\bdaily\s+(?:report|news|brief)\b|日报|\bbrand\s+mentions\b|"
               r"\b(?:trends|news|radar)\s+\d{4}-\d{2}-\d{2}\b|\brecruiter\s+search\b|\bpost:\s*\[?https://(?:x|twitter|www\.linkedin)\.com/")
CRYPTO = _rx(r"\b(?:usdc|usdt|eth|btc|sol|nft|airdrop|dao|gmv|on-?chain|wallet|web3|tokens?|rtc|defi|farcaster|zora)\b")
LEAD_MARKETPLACE_AD = _rx(r"\b(?:get|buy|generate)\s+(?:more\s+)?(?:qualified\s+)?(?:b2b\s+)?leads\b|\blead\s+generation\s+(?:service|platform|agency|software)\b|"
                          r"\bwe\s+connect\s+(?:businesses|clients|companies)\s+with\b|\bjoin\s+our\s+(?:marketplace|network)\s+of\s+(?:agencies|freelancers)\b")
SUPPORT_BUG = _rx(r"\bbug\b|\berror\b|\bexception\b|\bcrash\w*\b|\bstack\s?trace\b|\bdoes(?:n'?t| not)\s+work\b|\bnot\s+working\b|\bfails?\b|\bregression\b|\bbroken\b|\bfeat(?:ure)?\s*(?:request)?:|^feat\b|\bfix\b")
COMMERCIAL = _rx(r"\bpaid\b|\bpay\b|\bbudget\b|\bhire\b|\bhiring\b|\bquote\b|\bcontract\w*\b|\bfreelanc\w*\b|\bconsultan\w*\b|\bagency\b|[£$€]\s?\d|\b\d+\s?(?:gbp|usd|eur|aed)\b")
RECURRING = _rx(r"\bongoing\b|\bretainer\b|\bmonthly\b|\blong[\s-]?term\b|\brecurring\b|\bmaintenance\s+contract\b|\bmultiple\s+(?:projects|clients)\b")

TENDER_SOURCES = {"contracts_finder", "find_a_tender", "ted"}
FRESH_DAYS, STALE_DAYS = 30, 90


def _to_signal(rec: RawRecord) -> Signal:
    status = {"api_verified": "verified_api", "reviewer_verified": "human_verified", "user_submitted": "human_verified",
              "licensed_import": "human_verified", "search_snippet_only": "search_index_only", "fixture": "synthetic"}[rec.verification]
    meta = {"kind": "tender" if rec.source_key in TENDER_SOURCES else rec.meta.get("kind", "forum_post"), **rec.meta}
    return Signal(source=rec.source_key, source_id=rec.source_id, url=rec.url, title=rec.title, text=rec.body,
                  verification_status=status, posted_at=rec.created_at, organisation=rec.organisation,
                  country_hint=rec.country_hint, raw_meta=meta)


def _age(rec: RawRecord, now: datetime) -> Optional[int]:
    if not rec.created_at:
        return None
    try:
        dt = datetime.fromisoformat(rec.created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))).days


def assess(rec: RawRecord, now: Optional[datetime] = None) -> Assessment:
    now = now or datetime.now(timezone.utc)
    sig = _to_signal(rec)
    c = classify(sig, now=now)
    text = f"{rec.title}\n{rec.body}"
    pol = registry.policy(rec.source_key)
    family = pol["family"]
    ev = {g: [e.matched for e in c.evidence if e.group == g] for g in
          ("external_help", "scope", "vendor", "recruitment", "partner", "problem", "budget_or_project")}
    noise: list[str] = []
    missing: list[str] = []

    # ---- A. technical relevance (reused service-relevance model) ----------------------------
    rel = c.relevance or {}
    tech = Dimension(c.service_relevance, list(rel.get("positive") or [])[:5] + [f"against: {x}" for x in (rel.get("negative") or [])[:2]],
                     "high" if c.service_relevance in ("relevant", "not_relevant") and rec.body else "medium")

    # ---- noise detectors (new false-positive categories) ------------------------------------
    if SEO_CONTENT.search(rec.title):
        noise.append("seo_or_content_marketing")
    if LEAD_BOT.search(text) or LEAD_BOT.search(rec.url):
        noise.append("lead_aggregator_or_bot_post")
    if LEAD_MARKETPLACE_AD.search(text):
        noise.append("lead_marketplace_advertising")
    if CRYPTO.search(text) and (PAID_BOUNTY.search(text) or "paid" in text.lower()):
        noise.append("crypto_bounty_or_token_payment")
    if HOBBY.search(text):
        noise.append("hobby_or_personal_project")
    if c.service_relevance == "product_only":
        noise.append("licence_or_product_purchase")
    if rec.verification == "search_snippet_only":
        noise.append("search_snippet_only")

    # ---- B. buying intent ---------------------------------------------------------------------
    # A person looking for work is a job seeker; an agency/freelancer advertising services ("[For Hire]", "we offer") is a seller.
    if JOB_SEEKER.search(text) and not re.search(r"\bwe\s+offer\b|\bour\s+(?:agency|services)\b", text, re.I):
        intent = Dimension("job_seeker", [JOB_SEEKER.search(text).group(0)], "high")
    elif c.reject_reason == "vendor_self_promotion" or "seo_or_content_marketing" in noise or "lead_marketplace_advertising" in noise:
        intent = Dimension("seller_offer", ev["vendor"] or noise[:1], "high")
    elif c.reject_reason == "recruitment_or_staffing":
        intent = Dimension("employment_or_staffing", ev["recruitment"], "high")
    elif rec.source_key in TENDER_SOURCES:
        intent = Dimension("formal_procurement", ["public procurement notice"], "high")
    elif PARTNER_SEARCH.search(text) and (ev["external_help"] or INVITATION.search(text)):
        intent = Dimension("partner_search", [PARTNER_SEARCH.search(text).group(0)] + ev["external_help"][:2], "high")
    elif QUOTE.search(text):
        intent = Dimension("quote_request", [QUOTE.search(text).group(0)], "high")
    elif RECOMMENDATION.search(text):
        intent = Dimension("recommendation_request", [RECOMMENDATION.search(text).group(0)], "high")
    elif ev["external_help"]:
        intent = Dimension("explicit_hire_request", ev["external_help"][:3], "high" if len(ev["external_help"]) > 1 or ev["budget_or_project"] else "medium")
    elif PAID_BOUNTY.search(text) and COMMERCIAL.search(text) and "crypto_bounty_or_token_payment" not in noise:
        intent = Dimension("paid_bounty", [PAID_BOUNTY.search(text).group(0)], "medium")
    elif ev["problem"]:
        intent = Dimension("problem_only", ev["problem"], "medium")
    else:
        intent = Dimension("none_or_discussion", [], "medium")

    # Freelance marketplaces: a project posting / matched brief IS a request to hire, whatever its wording.
    if family == "freelance_marketplace" and intent.value in ("none_or_discussion", "problem_only") and c.service_relevance == "relevant":
        intent = Dimension("explicit_hire_request", [f"project/brief posted on {pol['name']}"], "medium")
    # Developer-community posts: buying intent requires the poster to solicit outside help; a stray "paid work" /
    # "hire" inside an internal task, release note or product feature is not a request (live GitHub run, 2026-11-06).
    if family == "developer_community" and intent.value in ("explicit_hire_request", "quote_request", "recommendation_request") \
            and not (SOLICIT.search(text) or INVITATION.search(text) or RECOMMENDATION.search(text)):
        noise.append("no_external_invitation")
        intent = Dimension("none_or_discussion", [f"intent words without solicitation: {', '.join(intent.evidence[:2])}"], "medium")
    # GitHub/forum items with no commercial wording and no invitation are not buyer signals
    if family == "developer_community" and intent.value in ("none_or_discussion", "problem_only") and not COMMERCIAL.search(text):
        noise.append("support_or_internal_task" if SUPPORT_BUG.search(text) else "no_external_invitation")

    # ---- C. engagement type -------------------------------------------------------------------
    if rec.source_key in TENDER_SOURCES:
        eng = Dimension("procurement", ["public procurement notice"], "high")
    elif intent.value == "paid_bounty":
        eng = Dimension("bounty", intent.evidence, "medium")
    else:
        eng = Dimension("unknown", [], "low")
        for name, rx in ENGAGEMENT:
            m = rx.search(text)
            if m:
                eng = Dimension(name, [m.group(0)], "medium")
                break
        if eng.value == "unknown" and family == "freelance_marketplace":
            eng = Dimension("freelance_project", [f"posted on {pol['name']}"], "medium")

    # ---- D. business type (self-reported evidence only) --------------------------------------
    emp = EMPLOYEES.search(text)
    if rec.source_key in TENDER_SOURCES or PUBLIC_SECTOR.search(text):
        biz = Dimension("public_sector", ["procurement notice" if rec.source_key in TENDER_SOURCES else PUBLIC_SECTOR.search(text).group(0)], "high")
    elif AGENCY.search(text):
        biz = Dimension("agency", [AGENCY.search(text).group(0)], "medium")
    elif ENTERPRISE.search(text):
        biz = Dimension("enterprise", [ENTERPRISE.search(text).group(0)], "medium")
    elif "hobby_or_personal_project" in noise:
        biz = Dimension("individual_or_hobby", [HOBBY.search(text).group(0)], "medium")
    elif SME.search(text):
        biz = Dimension("independent_sme_self_reported", [SME.search(text).group(0)], "low")
    elif family == "developer_community":
        biz = Dimension("open_source_or_unknown", ["developer-community post with no business description"], "low")
    else:
        biz = Dimension("unknown", [], "low")
        missing.append("organisation and size unknown")
    if emp:
        biz.evidence.append(f"self-reported size: {emp.group(0)}")

    # ---- E. decision-maker access ------------------------------------------------------------
    role = rec.stated_role or (DECISION_ROLE.search(text).group(0) if DECISION_ROLE.search(text) else None)
    if rec.source_key in TENDER_SOURCES:
        dm = Dimension("procurement_channel", ["contracting authority via the procurement portal"], "high")
    elif role:
        dm = Dimension("self_reported_decision_maker", [role], "low")
    else:
        dm = Dimension("poster_role_unknown", [], "low")
        missing.append("whether the poster can buy is unknown")

    # ---- F. freshness (date evidence and status kept separate) -------------------------------
    age = _age(rec, now)
    if rec.state == "closed":
        fresh = Dimension("closed", [f"source state: closed (created {rec.created_at})"], "high")
    elif age is None:
        fresh = Dimension("date_unknown", [], "low")
        missing.append("publication date unknown")
    else:
        band = "fresh" if age <= FRESH_DAYS else "stale" if age <= STALE_DAYS else "old"
        status = "status open per source (not proof it is still available)" if rec.state == "open" else "status unknown"
        fresh = Dimension(band, [f"created {rec.created_at} ({age} days)", status], "high" if rec.created_at else "low")

    # ---- G. delivery complexity --------------------------------------------------------------
    cx = Dimension(c.complexity, list(c.delivery_flags) + (["partnership may be needed"] if c.partnership_opportunity else []), "medium")

    # ---- H. evidence confidence ---------------------------------------------------------------
    if rec.verification in VERIFIED:
        conf = Dimension("verified_source_content", [f"{rec.verification} via {pol['name']}"], "high" if rec.body else "medium")
    elif rec.verification in ("user_submitted", "licensed_import"):
        conf = Dimension("user_supplied_unverified", [rec.verification], "low")
        missing.append("reviewer must open the original URL and confirm content and date")
    else:
        conf = Dimension("unverified", [rec.verification], "low")

    # ---- I. commercial potential (stated facts only) ----------------------------------------
    budget, gbp, kind = parse_budget(text)
    if rec.meta.get("budget"):
        budget, kind = str(rec.meta["budget"]), "stated_by_platform"
    pot_ev = [f"budget: {budget}"] if kind != "not_stated" else ["budget not stated"]
    if RECURRING.search(text):
        pot_ev.append(f"recurring hint: {RECURRING.search(text).group(0)}")
    if "crypto_bounty_or_token_payment" in noise:
        pot_ev.append("payment in crypto/tokens")
    pot = Dimension("budget_stated" if kind != "not_stated" else "not_stated", pot_ev, "high" if kind != "not_stated" else "low")

    # ---- J. contact permission ---------------------------------------------------------------
    rules = registry.marketplace_rules(rec.source_key) if family in ("freelance_marketplace", "lead_marketplace") else None
    if rec.source_key in TENDER_SOURCES:
        cp = Dimension("formal_procurement_only", [pol["contact_route"]], "high")
    elif rules:
        cp = Dimension("in_platform_only" if rules.get("off_platform_contact") is False else "per_platform_rules", [pol["contact_route"]], "medium")
    elif family == "developer_community":
        inv = INVITATION.search(text)
        cp = Dimension("reply_in_thread_invited" if inv else "no_unsolicited_outreach",
                       [inv.group(0)] if inv else ["no invitation to contact; GitHub AUP forbids spam/email harvesting"], "medium")
    elif family in ("social", "entrepreneur_community", "ecosystem_community"):
        cp = Dimension("platform_rules_apply", [pol["contact_route"]], "low")
        missing.append("check the community's solicitation rules before replying")
    else:
        cp = Dimension("unknown", [pol["contact_route"]], "low")

    loc = locate(sig, text)
    location = Dimension(loc.market, [loc.evidence] + [f"flag: {f}" for f in loc.flags], "medium" if loc.market != "unknown" else "low")
    if loc.market == "unknown":
        missing.append("location unknown")

    return Assessment(
        technical_relevance=tech, buying_intent=intent, engagement_type=eng, business_type=biz, decision_maker_access=dm,
        freshness=fresh, delivery_complexity=cx, evidence_confidence=conf, commercial_potential=pot, contact_permission=cp,
        location=location, noise_flags=sorted(set(noise)), suggested_service=c.suggested_service, missing_facts=missing,
    )
