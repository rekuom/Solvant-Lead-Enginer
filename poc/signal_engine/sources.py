"""Source permission registry.

A collector may run ONLY if `collection_permitted` is True here. Network reachability is
not permission. Each entry records the basis, the evidence checked and when, the contact
route the source makes legitimate, and any blocker.

To enable a blocked source: obtain and file the written permission (or a documented
licence/API terms that allow this use), update the entry with the evidence, and add a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SourcePolicy:
    key: str
    name: str
    collection_permitted: bool
    basis: str
    evidence: tuple[str, ...]
    checked_on: str
    contact_route: str
    contact_permitted: Optional[bool]
    attribution: str = ""
    blocker: str = ""
    access_notes: str = ""
    max_requests_per_run: int = 20
    tags: tuple[str, ...] = field(default_factory=tuple)


SOURCES: dict[str, SourcePolicy] = {
    "contracts_finder": SourcePolicy(
        key="contracts_finder", name="UK Contracts Finder (OCDS API)",
        collection_permitted=True,
        basis="Open Government Licence v3.0 (commercial reuse allowed with attribution); documented public API; no robots.txt (404).",
        evidence=("https://www.contractsfinder.service.gov.uk/apidocumentation/Notices/1/GET-Published-Notice-OCDS-Search",
                  "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                  "GitHub Actions run 42032803184: OCDS search 200 JSON; robots.txt 404"),
        checked_on="2026-11-05",
        contact_route="Respond through the published procurement process (contact point on the notice).",
        contact_permitted=True,
        attribution="Contains public sector information licensed under the Open Government Licence v3.0.",
        access_notes="HTML notice pages return 403 to automated clients (bot protection): use the API only; humans open the notice URL in a browser.",
        max_requests_per_run=12, tags=("tender", "UK"),
    ),
    "find_a_tender": SourcePolicy(
        key="find_a_tender", name="UK Find a Tender (OCDS API)",
        collection_permitted=True,
        basis="Open Government Licence v3.0; official 'Data and API documentation'; no robots.txt (404).",
        evidence=("https://www.find-tender.service.gov.uk/Developer/Documentation",
                  "https://data.open-contracting.org/en/publication/41",
                  "GitHub Actions run 42032803184: ocdsReleasePackages 200 JSON; robots.txt 404"),
        checked_on="2026-11-05",
        contact_route="Respond through the published procurement process.",
        contact_permitted=True,
        attribution="Contains public sector information licensed under the Open Government Licence v3.0.",
        access_notes="HTML notice pages return 403 to automated clients: API only.",
        max_requests_per_run=5, tags=("tender", "UK"),
    ),
    "ted": SourcePolicy(
        key="ted", name="EU Tenders Electronic Daily (TED Search API v3)",
        collection_permitted=True,
        basis="TED legal notice: published notices may be reused for commercial or non-commercial purposes with credit and "
              "indication of changes; the Search API allows anonymous access to published notices.",
        evidence=("https://ted.europa.eu/en/legal-notice", "https://docs.ted.europa.eu/api/latest/search.html",
                  "https://ted.europa.eu/en/simap/developers-corner-for-reusers"),
        checked_on="2026-11-05",
        contact_route="Respond through the procurement procedure named on the notice (often a national e-procurement platform).",
        contact_permitted=True,
        attribution="Source: TED – Tenders Electronic Daily, © European Union. Changes: excerpted and classified.",
        access_notes="Not yet reached from any runner: first live run confirms field names and query syntax.",
        max_requests_per_run=4, tags=("tender", "Europe"),
    ),
    "discourse:community.n8n.io": SourcePolicy(
        key="discourse:community.n8n.io", name="n8n Community – Jobs",
        collection_permitted=False,
        basis="Not established. Public JSON is reachable (run 42032803184) but the forum terms have not been reviewed "
              "by a person and no permission for commercial collection has been obtained.",
        evidence=("https://community.n8n.io/tos", "https://community.n8n.io/robots.txt"),
        checked_on="2026-11-05",
        contact_route="Reply on the job thread, as the Jobs board intends (manual).",
        contact_permitted=True,
        blocker="Written permission from n8n (community owner) or a documented terms clause allowing automated commercial "
                "collection. Until then: manual review only (human capture).",
        tags=("forum",),
    ),
    "discourse:community.make.com": SourcePolicy(
        key="discourse:community.make.com", name="Make Community – Hire a Pro",
        collection_permitted=False,
        basis="Not established. Public JSON is reachable (run 42032803184) but the forum terms have not been reviewed "
              "by a person and no permission for commercial collection has been obtained.",
        evidence=("https://community.make.com/tos", "https://community.make.com/robots.txt"),
        checked_on="2026-11-05",
        contact_route="Reply on the Hire a Pro thread, as the category intends (manual).",
        contact_permitted=True,
        blocker="Written permission from Make (community owner) or a documented terms clause allowing automated commercial "
                "collection. Until then: manual review only (human capture).",
        tags=("forum",),
    ),
}

UNKNOWN_SOURCE = SourcePolicy(
    key="unknown", name="unknown", collection_permitted=False, basis="unknown", evidence=(), checked_on="",
    contact_route="unknown", contact_permitted=None, blocker="not in registry")


def policy(key: str) -> SourcePolicy:
    if key.startswith("human:"):
        return SourcePolicy(key=key, name="Human capture", collection_permitted=False,
                            basis="A person opened the page and recorded it manually; platform terms apply to any outreach.",
                            evidence=(), checked_on="", contact_route="per platform rules (check before contacting)",
                            contact_permitted=None)
    return SOURCES.get(key, UNKNOWN_SOURCE)


def permitted(key: str) -> bool:
    return policy(key).collection_permitted


def permitted_collectors() -> list[str]:
    return [k for k, p in SOURCES.items() if p.collection_permitted]


def blocked_collectors() -> list[str]:
    return [k for k, p in SOURCES.items() if not p.collection_permitted]


class PermissionNotObtained(RuntimeError):
    pass


def require(key: str) -> None:
    """Called at the top of every collector. Raises unless automated collection is permitted."""
    pol = policy(key)
    if not pol.collection_permitted:
        raise PermissionNotObtained(f"{key}: automated collection not permitted — {pol.blocker or pol.basis}")
