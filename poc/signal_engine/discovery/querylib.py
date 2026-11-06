"""Query library + planner: categories × languages × providers, with repeat prevention,
per-provider quotas, cost estimates and a dry-run plan. A planned query is NOT a result."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

LIB = Path(__file__).resolve().parent / "data" / "query_library.json"

# Cost per request in USD (0 = free official API). Estimates, not invoices.
PROVIDER_COST = {"github": 0.0, "hn": 0.0, "brave": 0.005, "fixture": 0.0}
PROVIDER_LANGS = {"github": {"en"}, "hn": {"en"}}   # communities that are overwhelmingly English


@dataclass
class PlannedQuery:
    query_id: str
    provider: str
    category: str
    lang: str
    text: str
    query: str
    translation_confidence: str
    est_cost_usd: float

    def to_dict(self) -> dict:
        return asdict(self)


def load_library() -> dict:
    return json.loads(LIB.read_text())


def plan(provider: str, since: str, categories: Optional[Iterable[str]] = None, langs: Optional[Iterable[str]] = None,
         max_queries: int = 20) -> list[PlannedQuery]:
    lib = load_library()
    cats = set(categories or lib["categories"])
    allowed = set(langs or PROVIDER_LANGS.get(provider, set(lib["languages"])))
    out: list[PlannedQuery] = []
    # round-robin across categories so a small budget still covers every intent type
    by_cat: dict[str, list[dict]] = {}
    for p in lib["phrases"]:
        if p.get("providers") and provider not in p["providers"]:
            continue
        if p["category"] in cats and p["lang"] in allowed:
            by_cat.setdefault(p["category"], []).append(p)
    queues = [list(v) for _, v in sorted(by_cat.items())]
    while queues and len(out) < max_queries:
        for q in list(queues):
            if not q:
                queues.remove(q)
                continue
            p = q.pop(0)
            text = p["text"]
            if provider == "github":
                term = text if p.get("raw_query") else f'"{text}"'
                query = f"{term} " + lib["github_suffix"].format(since=since)
            else:
                query = f'"{text}"'
            out.append(PlannedQuery(f"{provider}:{p['id']}", provider, p["category"], p["lang"], text, query,
                                    p["translation_confidence"], PROVIDER_COST.get(provider, 0.0)))
            if len(out) >= max_queries:
                break
    return out


class QueryLog:
    """Prevents repeating the same provider+query within `ttl_hours` (persisted between runs when a path is given)."""

    def __init__(self, path: Optional[Path] = None, ttl_hours: int = 20) -> None:
        self.path = path
        self.ttl = timedelta(hours=ttl_hours)
        self.entries: dict[str, dict] = json.loads(path.read_text()) if path and path.exists() else {}

    @staticmethod
    def key(q: PlannedQuery) -> str:
        return hashlib.sha256(f"{q.provider}|{q.query}".encode()).hexdigest()[:16]

    def seen_recently(self, q: PlannedQuery, now: Optional[datetime] = None) -> bool:
        e = self.entries.get(self.key(q))
        if not e:
            return False
        now = now or datetime.now(timezone.utc)
        return now - datetime.fromisoformat(e["at"]) < self.ttl

    def record(self, q: PlannedQuery, results: int, status: str, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.entries[self.key(q)] = {"at": now.isoformat(), "query_id": q.query_id, "results": results, "status": status}

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.entries, indent=1))
