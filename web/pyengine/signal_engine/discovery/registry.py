"""Source-access policy registry (data in data/source_registry.json).

Policy is kept separate from classification. A connector may run only when its source
status is `permitted` — or `restricted` AND the operator explicitly opted in for that run
(after reviewing the terms). manual_only / licensed sources are intake-only. unknown and
prohibited never run.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

PATH = Path(__file__).resolve().parent / "data" / "source_registry.json"
STATUSES = ("permitted", "restricted", "manual_only", "licensed", "unknown", "prohibited")
BUILT = {"ocds", "ted", "github", "hn", "feeds", "search", "discourse", "intake"}
REQUIRED = ("key", "name", "family", "status", "collection", "pipelines", "contact_route", "evidence", "review_date", "notes")


class PolicyError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load() -> dict[str, dict]:
    data = json.loads(PATH.read_text())
    out: dict[str, dict] = {}
    for s in data["sources"]:
        missing = [k for k in REQUIRED if k not in s]
        if missing:
            raise PolicyError(f"{s.get('key')}: missing {missing}")
        if s["status"] not in STATUSES:
            raise PolicyError(f"{s['key']}: bad status {s['status']}")
        if s["key"] in out:
            raise PolicyError(f"duplicate key {s['key']}")
        out[s["key"]] = s
    return out


def policy(key: str) -> dict:
    src = load().get(key)
    if src is None:
        raise PolicyError(f"source {key!r} is not in the registry")
    return src


def may_collect(key: str, allow_restricted: Iterable[str] = ()) -> tuple[bool, str]:
    """Return (allowed, reason). Automated collection only; intake has its own rule."""
    p = policy(key)
    st = p["status"]
    if p["collection"] not in ("api", "feed", "search"):
        return False, f"{key}: collection mode '{p['collection']}' is not automated"
    if st == "permitted":
        return True, "permitted"
    if st == "restricted" and key in set(allow_restricted):
        return True, "restricted: operator opted in for this run after reviewing the terms"
    if st == "licensed" and p["collection"] == "search":
        return False, f"{key}: licensed search provider — needs an API key / paid plan (disabled)"
    return False, f"{key}: status '{st}' — {p['notes'][:160]}"


def may_intake(key: str) -> tuple[bool, str]:
    """Manual / alert / licensed-file intake is allowed for manual_only, licensed, permitted and restricted sources,
    because the user supplies records they are entitled to; prohibited and unknown sources are flagged for review."""
    p = policy(key)
    if p["status"] == "prohibited":
        return False, f"{key}: prohibited"
    if p["status"] == "unknown":
        return True, f"{key}: terms unknown — record kept for review only"
    return True, p["status"]


def marketplace_rules(key: str) -> dict:
    p = policy(key)
    return p.get("marketplace_rules") or {"can_submit_proposal": "unknown", "off_platform_contact": "unknown",
                                          "export_or_retain": "unknown", "agency_accounts": "unknown"}


def table_markdown() -> str:
    L = ["| Source | Family | Status | Automated collection | Pipelines | Contact route | Buying-intent quality | Cost | Notes |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s in load().values():
        ok, _ = may_collect(s["key"])
        built = s.get("connector") in BUILT
        auto = ("enabled" if ok and built else "permitted; connector not built" if ok else
                "built, disabled (needs opt-in/permission/credentials)" if built and s["collection"] in ("api", "search") else "no")
        L.append(f"| {s['name']} | {s['family']} | **{s['status']}** | {auto} | {', '.join(s['pipelines']) or '—'} | "
                 f"{s['contact_route']} | {s['buying_intent_quality']} | {s.get('cost', '')} | {s['notes'].replace('|', '/')} |")
    return "\n".join(L) + "\n"
