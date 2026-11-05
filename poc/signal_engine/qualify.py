"""Tasks 2–3 — strict commercial qualification.

Turns (Signal, Classification) into a review record with every field the business
asked for. Anything not evidenced in the source is the literal string "unknown".

Key distinctions:
  * intent_verified        – we saw the source content and it shows Tier A/B intent.
  * availability           – verified_open (future deadline in the source),
                             no_visible_closure (not closed, but NOT proof it is open),
                             closed, or unknown.
A lead is QUALIFIED only if every gate passes. Missing evidence never passes a gate.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .classify import Classification, _parse_dt
from .models import Signal

MAX_AGE_DAYS = 30
FIT_MIN_GBP, FIT_MAX_GBP, STRETCH_MAX_GBP = 500, 5000, 10000
_FX = {"£": 1.0, "GBP": 1.0, "$": 0.78, "USD": 0.78, "€": 0.85, "EUR": 0.85, "AED": 0.21}  # rough, banding only
_MONEY = re.compile(r"(?P<cur>£|\$|€|\b(?:GBP|USD|EUR|AED)\b)\s?(?P<amt>\d[\d,]*(?:\.\d+)?)\s?(?P<k>k\b)?"
                    r"|(?P<amt2>\d[\d,]*(?:\.\d+)?)\s?(?P<k2>k\b)?\s?(?P<cur2>\b(?:GBP|USD|EUR|AED)\b)", re.I)
_HOURLY = re.compile(r"/\s?(?:hr|hour)\b|\bper\s+hour\b|\bhourly\b", re.I)

SOURCE_POLICY = {
    "contracts_finder": {
        "data_use": "permitted — Open Government Licence v3.0 (attribute the source)",
        "contact_route": "respond through the published procurement process (buyer contact on the notice)",
        "contact_permitted": True,
    },
    "find_a_tender": {
        "data_use": "permitted — Open Government Licence v3.0 (attribute the source)",
        "contact_route": "respond through the published procurement process",
        "contact_permitted": True,
    },
    "discourse:community.n8n.io": {
        "data_use": "unconfirmed — forum terms not reviewed and owner permission not obtained; manual review only",
        "contact_route": "reply on the job thread / forum message, as the Jobs board intends",
        "contact_permitted": True,
    },
    "discourse:community.make.com": {
        "data_use": "unconfirmed — forum terms not reviewed and owner permission not obtained; manual review only",
        "contact_route": "reply on the Hire a Pro thread / forum message, as the category intends",
        "contact_permitted": True,
    },
}
UNKNOWN_POLICY = {"data_use": "unknown", "contact_route": "unknown", "contact_permitted": None}

# Location evidence must be a place, never a currency symbol ("£" does not prove the buyer is in the UK).
_PLACE = {
    "UK": re.compile(r"\b(?:uk|u\.k\.|united\s+kingdom|great\s+britain|england|scotland|wales|northern\s+ireland|london|"
                     r"manchester|birmingham|leeds|glasgow|edinburgh|bristol|liverpool|sheffield|newcastle|cardiff|belfast|"
                     r"nottingham|leicester|brighton|reading|cambridge|oxford)\b", re.I),
    "UAE": re.compile(r"\b(?:uae|u\.a\.e\.|united\s+arab\s+emirates|dubai|abu\s+dhabi|sharjah|ajman|ras\s+al\s+khaimah|"
                      r"fujairah|umm\s+al\s+quwain)\b", re.I),
}
_OTHER_PLACE = re.compile(r"\b(?:usa|u\.s\.a?\.|united\s+states|us[\s-]based|canada|australia|new\s+zealand|india|pakistan|"
                          r"philippines|germany|france|spain|italy|netherlands|brazil|mexico|nigeria|south\s+africa|singapore|"
                          r"saudi\s+arabia|qatar|ohio|texas|california|new\s+york|florida)\b", re.I)

# Work Solvant should not take on from these sources.
_NOT_DELIVERABLE = re.compile(r"\bblue\s?prism\b|\buipath\s+(?:centre|center)\s+of\s+excellence\b|\bframework\s+agreement\b"
                              r"|\bdynamic\s+purchasing\s+system\b|\bmanaged\s+service\b", re.I)


@dataclass
class QualRecord:
    url: str
    source: str
    verification_status: str
    title: str
    published_at: str
    age_days: Optional[int]
    buyer_request: str
    external_provider_evidence: list[str]
    country: str
    location_evidence: str
    scope: str
    budget_stated: str
    budget_gbp_max: Optional[float]
    budget_fit: str                 # fit / stretch / out / too_small / hourly_only / unknown
    availability: str               # verified_open / no_visible_closure / closed / unknown
    availability_basis: str
    data_use: str
    contact_route: str
    contact_permitted: Optional[bool]
    deliverable: str                # yes / no / unknown
    deliverable_basis: str
    intent_tier: str
    actionable: str
    intent_verified: bool
    suggested_service: str
    qualification: str              # QUALIFIED / NEEDS_REVIEW / EXCLUDED
    reasons: list[str] = field(default_factory=list)
    organisation: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


def parse_budget(text: str) -> tuple[str, Optional[float], str]:
    found, gbp = [], []
    for m in _MONEY.finditer(text):
        cur = (m.group("cur") or m.group("cur2") or "").upper()
        amt = m.group("amt") or m.group("amt2")
        k = m.group("k") or m.group("k2")
        try:
            v = float(amt.replace(",", "")) * (1000 if k else 1)
        except ValueError:
            continue
        found.append(m.group(0).strip())
        gbp.append(v * _FX.get(cur, _FX.get(cur.strip(), 1.0)))
    if not found:
        return "unknown", None, "unknown"
    mx = max(gbp)
    if _HOURLY.search(text):
        return "; ".join(found), mx, "hourly_only"
    if mx > STRETCH_MAX_GBP:
        fit = "out"
    elif mx > FIT_MAX_GBP:
        fit = "stretch"
    elif mx < FIT_MIN_GBP:
        fit = "too_small"
    else:
        fit = "fit"
    return "; ".join(found), mx, fit


def _location(sig: Signal, text: str, c: Classification) -> tuple[str, str]:
    if sig.source in ("contracts_finder", "find_a_tender") and sig.verification_status != "search_index_only":
        return "UK", "UK public-sector procurement notice"
    for country, rx in _PLACE.items():
        m = rx.search(text)
        if m:
            return country, f"text mentions '{m.group(0)}'"
    m = _OTHER_PLACE.search(text)
    if m:
        return "other", f"text mentions '{m.group(0)}'"
    return "unknown", "unknown"


def _availability(sig: Signal, now: datetime) -> tuple[str, str]:
    if sig.verification_status == "search_index_only":
        return "unknown", "page not opened"
    deadline = _parse_dt(sig.deadline_at)
    if deadline is not None:
        return ("verified_open", f"deadline {sig.deadline_at} is in the future") if deadline > now \
            else ("closed", f"deadline {sig.deadline_at} has passed")
    status = (sig.raw_meta or {}).get("tender_status")
    if status in ("complete", "cancelled", "unsuccessful", "withdrawn"):
        return "closed", f"tender status '{status}'"
    if (sig.raw_meta or {}).get("closed") or (sig.raw_meta or {}).get("archived"):
        return "closed", "topic is closed/archived on the forum"
    if (sig.raw_meta or {}).get("kind") == "forum_post":
        return "no_visible_closure", "topic open on forum; poster may already have hired (not proof of availability)"
    return "unknown", "no deadline or status in source"


def qualify(sig: Signal, c: Classification, now: Optional[datetime] = None) -> QualRecord:
    now = now or datetime.now(timezone.utc)
    text = f"{sig.title}\n{sig.text}"
    posted = _parse_dt(sig.posted_at)
    age = (now - posted).days if posted else None
    country, loc_ev = _location(sig, text, c)
    budget_str, budget_gbp, fit = parse_budget(text)
    if fit == "unknown" and sig.value_amount:
        cur = (sig.value_currency or "GBP").upper()
        budget_gbp = sig.value_amount * _FX.get(cur, 1.0)
        budget_str = f"{cur} {sig.value_amount:,.0f} (notice value)"
        fit = "out" if budget_gbp > STRETCH_MAX_GBP else "stretch" if budget_gbp > FIT_MAX_GBP else \
              "too_small" if budget_gbp < FIT_MIN_GBP else "fit"
    avail, avail_basis = _availability(sig, now)
    pol = SOURCE_POLICY.get(sig.source, UNKNOWN_POLICY)
    ext = [e.matched for e in c.evidence if e.group == "external_help"]
    scope_feats = sorted({e.feature for e in c.evidence if e.group == "scope"})

    if c.intent_tier == "REJECT" or c.reject_reason == "unrelated_physical_or_industrial_automation":
        deliverable, d_basis = "no", c.reject_reason or "rejected"
    elif _NOT_DELIVERABLE.search(text):
        deliverable, d_basis = "no", "enterprise framework / specialist platform work beyond a small automation studio"
    elif fit == "out":
        deliverable, d_basis = "no", "value far above £1–3k packages"
    elif c.intent_tier in ("A", "B", "C") and scope_feats:
        deliverable, d_basis = "yes", f"scope matches Solvant services ({', '.join(scope_feats)})"
    else:
        deliverable, d_basis = "unknown", "scope not specific enough"

    genuine = sig.is_genuine
    intent_verified = genuine and c.intent_tier in ("A", "B")
    reasons: list[str] = []
    hard_exclude = False
    if sig.verification_status == "synthetic":
        reasons.append("synthetic fixture"); hard_exclude = True
    if not genuine and sig.verification_status != "synthetic":
        reasons.append("source content not verified (search title only)")
    if c.reject_reason in ("vendor_self_promotion", "recruitment_or_staffing",
                           "unrelated_physical_or_industrial_automation", "unrelated_no_automation_scope"):
        reasons.append(c.reject_reason); hard_exclude = True
    if c.intent_tier in ("C", "D"):
        reasons.append(f"intent tier {c.intent_tier} (no explicit request to hire)"); hard_exclude = True
    if age is None:
        reasons.append("publication date unknown")
    elif age > MAX_AGE_DAYS:
        reasons.append(f"stale: {age} days old"); hard_exclude = True
    if country == "unknown":
        reasons.append("UK/UAE location not evidenced")
    elif country not in ("UK", "UAE"):
        reasons.append(f"outside UK/UAE ({country})"); hard_exclude = True
    if avail == "closed":
        reasons.append("closed"); hard_exclude = True
    if fit == "out":
        reasons.append("budget far above £1–3k"); hard_exclude = True
    if deliverable == "no" and "budget far above £1–3k" not in reasons and c.intent_tier != "REJECT":
        reasons.append(f"not deliverable: {d_basis}"); hard_exclude = True

    if hard_exclude:
        verdict = "EXCLUDED"
    elif reasons:
        verdict = "NEEDS_REVIEW"
    else:
        verdict = "QUALIFIED"

    return QualRecord(
        url=sig.url, source=sig.source, verification_status=sig.verification_status, title=sig.title,
        published_at=sig.posted_at or "unknown", age_days=age,
        buyer_request=(sig.text[:400] if sig.text else "unknown (body not retrieved)"),
        external_provider_evidence=ext or ["none found"],
        country=country, location_evidence=loc_ev,
        scope=", ".join(scope_feats) or "unknown",
        budget_stated=budget_str, budget_gbp_max=budget_gbp, budget_fit=fit,
        availability=avail, availability_basis=avail_basis,
        data_use=pol["data_use"], contact_route=pol["contact_route"], contact_permitted=pol["contact_permitted"],
        deliverable=deliverable, deliverable_basis=d_basis,
        intent_tier=c.intent_tier, actionable=c.actionable, intent_verified=intent_verified,
        suggested_service=c.suggested_service or "—",
        qualification=verdict, reasons=reasons, organisation=sig.organisation or "unknown",
    )
