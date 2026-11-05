"""Core data model for a collected signal."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# How much we trust that the stored text is what the source actually says.
#   verified_api       – text retrieved directly from an official/authorised API
#                        response by this pipeline. Only these count as genuine.
#   search_index_only  – URL + title came from a web-search index; the page itself
#                        was NOT fetched. Must be human-verified before outreach.
#   synthetic          – hand-written test fixture. Never a lead. Never counted.
VERIFICATION_STATUSES = ("verified_api", "search_index_only", "synthetic")


@dataclass
class Signal:
    source: str                      # e.g. "contracts_finder", "discourse:community.n8n.io"
    source_id: str                   # stable id within the source
    url: str                         # original evidence URL
    title: str
    text: str                        # excerpt (redacted, length-capped)
    verification_status: str
    posted_at: Optional[str] = None  # ISO-8601 from the source, if provided
    collected_at: Optional[str] = None
    deadline_at: Optional[str] = None  # tenders: tender period end
    author_handle: Optional[str] = None  # public handle only, never personal contact data
    organisation: Optional[str] = None   # only when the source publishes it (e.g. tender buyer)
    country_hint: Optional[str] = None   # "UK" / "UAE" / None
    value_amount: Optional[float] = None
    value_currency: Optional[str] = None
    raw_meta: dict[str, Any] = field(default_factory=dict)  # provenance, never PII

    def __post_init__(self) -> None:
        if self.verification_status not in VERIFICATION_STATUSES:
            raise ValueError(f"bad verification_status {self.verification_status!r}")
        if not self.url.startswith("https://"):
            raise ValueError(f"evidence URL must be https: {self.url!r}")

    @property
    def is_genuine(self) -> bool:
        """A signal counts toward the 'genuine' total only if fetched from the source."""
        return self.verification_status == "verified_api"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
