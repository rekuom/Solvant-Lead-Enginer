"""Canonical discovery data model.

Raw source evidence (RawRecord) is kept strictly separate from interpretation (Assessment)
and from routing (Opportunity). Nothing in RawRecord is ever inferred.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# How the CONTENT was obtained. Only the first two count as verified source content.
VERIFICATION = (
    "api_verified",          # fetched from an official API by a connector
    "reviewer_verified",     # a named reviewer opened the original page and confirmed the content/date
    "user_submitted",        # manual / imported entry: content as supplied, NOT yet verified
    "licensed_import",       # purchased/licensed lead feed row: content per the licence, not independently verified
    "search_snippet_only",   # a search-engine result: title/snippet only
    "fixture",               # test data; never a lead
)
VERIFIED = {"api_verified", "reviewer_verified"}

PIPELINES = {
    "A_DIRECT_SME": "Direct buyers (SME first): explicit request for external implementation help",
    "B_FREELANCE_PROJECT": "Freelance / project marketplaces: a real posted project accepting contractors",
    "C_AGENCY_PARTNER": "Agency partnerships: white-label, subcontract, delivery partner",
    "D_OPERATIONAL_PAIN": "Operational pain: specific problem, no explicit request to hire",
    "E_PROCUREMENT": "Enterprise and government procurement",
    "F_RECRUITMENT_SIGNAL": "Recruitment and hiring signals (not consultancy demand)",
    "G_LICENSED_LEADS": "Purchased or licensed leads",
    "H_RESEARCH_UNVERIFIED": "Research and unverified discoveries (never presented as buyers)",
    "GLOBAL_REVIEW": "Strong opportunity outside the target markets (kept for review)",
    "EXCLUDED": "Excluded with a recorded reason",
}


@dataclass
class RawRecord:
    """Exactly what the source said, plus provenance. No interpretation."""
    source_key: str                     # registry key, e.g. "github_issues"
    source_id: str                      # stable id within the source
    url: str
    title: str
    body: str                           # excerpt as obtained (already PII-redacted)
    verification: str
    created_at: Optional[str] = None    # source publication time (ISO)
    updated_at: Optional[str] = None
    state: Optional[str] = None         # open / closed / unknown — as reported by the source
    fetched_at: Optional[str] = None
    query_id: Optional[str] = None      # which query/feed/import produced it
    language: Optional[str] = None
    author_ref: Optional[str] = None    # salted hash of the author handle — never the handle itself
    author_kind: Optional[str] = None   # e.g. GitHub user.type, "unknown"
    organisation: Optional[str] = None  # only when the source states it
    country_hint: Optional[str] = None
    stated_role: Optional[str] = None   # role as publicly presented by the poster (manual capture), e.g. "founder"
    labels: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)   # source-specific facts (comments count, platform, budget field…)

    def __post_init__(self) -> None:
        if self.verification not in VERIFICATION:
            raise ValueError(f"bad verification {self.verification!r}")
        if not self.url.startswith("https://"):
            raise ValueError(f"evidence URL must be https: {self.url!r}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Dimension:
    value: str
    evidence: list[str] = field(default_factory=list)
    confidence: str = "low"             # low / medium / high — how well the evidence supports the value


@dataclass
class Assessment:
    """Independent dimensions (A–J). Each carries its own evidence; none is derived from a single score."""
    technical_relevance: Dimension
    buying_intent: Dimension
    engagement_type: Dimension
    business_type: Dimension
    decision_maker_access: Dimension
    freshness: Dimension
    delivery_complexity: Dimension
    evidence_confidence: Dimension
    commercial_potential: Dimension
    contact_permission: Dimension
    location: Dimension
    noise_flags: list[str] = field(default_factory=list)
    suggested_service: Optional[str] = None
    missing_facts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Opportunity:
    record: RawRecord
    assessment: Assessment
    pipeline: str
    pipeline_reason: str
    rank_score: int = 0
    rank_explanation: list[str] = field(default_factory=list)
    next_action: str = ""
    duplicate_of: Optional[str] = None

    def to_dict(self) -> dict:
        return {"record": self.record.to_dict(), "assessment": self.assessment.to_dict(), "pipeline": self.pipeline,
                "pipeline_reason": self.pipeline_reason, "rank_score": self.rank_score,
                "rank_explanation": self.rank_explanation, "next_action": self.next_action, "duplicate_of": self.duplicate_of}
