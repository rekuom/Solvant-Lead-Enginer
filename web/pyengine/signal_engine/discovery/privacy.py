"""Privacy helpers. The repository is PUBLIC: nothing personal may reach commits, logs or artifacts.

* Author handles are replaced by a salted hash (author_ref). The salt comes from the environment
  (DISCOVERY_SALT) so refs are stable within a deployment but not reversible from the repo.
* Excerpts reuse textutil.make_excerpt (emails, phones, labelled contact names removed).
* `public_view` produces the redacted form allowed in Actions artifacts / summaries.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Optional

from ..textutil import make_excerpt

_HANDLE = re.compile(r"(?<![\w/])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,38}")


def author_ref(handle: Optional[str]) -> Optional[str]:
    if not handle:
        return None
    salt = os.environ.get("DISCOVERY_SALT", "solvant-discovery-default-salt")
    return "a_" + hashlib.sha256(f"{salt}:{handle.lower()}".encode()).hexdigest()[:12]


def clean_text(raw: str, limit: int = 800) -> str:
    """Excerpt with PII removed and @handles masked."""
    return _HANDLE.sub("@[user]", make_excerpt(raw or "", limit=limit))


# Only these record.meta keys may appear in public artifacts (no reviewer names, notes, handles or raw platform payloads).
PUBLIC_META = {"kind", "query_category", "discovered_via", "verification_route", "deadline_at", "tender_status", "cpv",
               "budget", "landing_source", "market"}


def public_view(opp: dict) -> dict:
    """Redacted opportunity for public artifacts: no author refs, no stated roles tied to people, short re-cleaned
    excerpt (emails/phones/handles removed again), allow-listed meta only."""
    rec = dict(opp["record"])
    rec.pop("author_ref", None)
    rec.pop("stated_role", None)
    rec["title"] = clean_text(rec.get("title") or "", limit=200)
    rec["body"] = clean_text(rec.get("body") or "", limit=400)
    rec["meta"] = {k: v for k, v in (rec.get("meta") or {}).items() if k in PUBLIC_META}
    return {**opp, "record": rec}
