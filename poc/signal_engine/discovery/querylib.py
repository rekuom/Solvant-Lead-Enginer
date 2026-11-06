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
    market: Optional[str] = None        # web search only: target market this query is aimed at
    country: Optional[str] = None       # provider country parameter (e.g. Brave `country`)
    search_lang: Optional[str] = None   # provider language parameter (e.g. Brave `search_lang`)

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


# ----------------------------------------------------------------------------- web search (Brave) market plan
# Brave `country` accepts only a documented subset (~35 + ALL; UAE, Ireland, Romania, Czechia etc. are NOT in it),
# so unsupported markets use country=ALL plus a location term in the query. search_lang codes per Brave's codes page.
BRAVE_COUNTRIES = {"AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE", "HK", "IN", "ID", "IT", "JP", "KR", "MY", "MX",
                   "NL", "NZ", "NO", "CN", "PL", "PT", "PH", "RU", "SA", "ZA", "ES", "SE", "CH", "TW", "TR", "GB", "US", "ALL"}
# lang -> list of (market label, country code, location term or None, brave search_lang)
WEB_MARKETS = {
    "en": [("UK", "GB", None, "en-gb"), ("UAE", "ALL", "Dubai", "en"), ("Ireland", "ALL", "Ireland", "en")],
    "de": [("Germany", "DE", None, "de"), ("Switzerland", "CH", None, "de"), ("Austria", "AT", None, "de")],
    "fr": [("France", "FR", None, "fr"), ("Belgium", "BE", None, "fr")],
    "es": [("Spain", "ES", None, "es")], "nl": [("Netherlands", "NL", None, "nl")], "it": [("Italy", "IT", None, "it")],
    "pt": [("Portugal", "PT", None, "pt-pt")], "pl": [("Poland", "PL", None, "pl")], "ro": [("Romania", "ALL", "România", "ro")],
    "sv": [("Sweden", "SE", None, "sv")], "no": [("Norway", "NO", None, "nb")], "da": [("Denmark", "DK", None, "da")],
    "fi": [("Finland", "FI", None, "fi")], "cs": [("Czechia", "ALL", "Česko", "cs")],
}
# Direct external-provider requests first; problem statements get a small share. Weights = share of the request budget.
WEB_WEIGHTS = {"explicit_project_request": 0.30, "external_provider_search": 0.20, "recommendation_request": 0.15,
               "agency_partnership": 0.15, "freelancer_hiring": 0.10, "problem_statement": 0.06, "implementation_blocker": 0.04}
WEB_PRIORITY = ["explicit_project_request", "external_provider_search", "recommendation_request", "agency_partnership",
                "freelancer_hiring", "problem_statement", "implementation_blocker"]


def plan_web(provider: str = "brave", max_requests: int = 100, categories: Optional[Iterable[str]] = None) -> list[PlannedQuery]:
    """One request per (phrase, market). Round-robin over priority categories and languages so 100 requests
    cover every market; English phrases are spread over UK / UAE / Ireland."""
    lib = load_library()
    cats = [c for c in WEB_PRIORITY if not categories or c in set(categories)]
    pools: dict[str, list[PlannedQuery]] = {c: [] for c in cats}
    for p in lib["phrases"]:
        if p["category"] not in pools or (p.get("providers") and provider not in p["providers"]):
            continue
        for market, country, loc, slang in WEB_MARKETS.get(p["lang"], []):
            query = f'"{p["text"]}"' + (f" {loc}" if loc else "")
            pools[p["category"]].append(PlannedQuery(f"{provider}:{p['id']}:{market}", provider, p["category"], p["lang"], p["text"],
                                                     query, p["translation_confidence"], PROVIDER_COST.get(provider, 0.0),
                                                     market=market, country=country if country in BRAVE_COUNTRIES else "ALL",
                                                     search_lang=slang))
    # interleave languages inside each category so non-English markets are not starved
    for c in cats:
        by_lang: dict[str, list[PlannedQuery]] = {}
        for q in pools[c]:
            by_lang.setdefault(q.lang, []).append(q)
        mixed: list[PlannedQuery] = []
        while any(by_lang.values()):
            for lang in sorted(by_lang, key=lambda l: (l != "en", l)):   # English (UK/UAE/IE) first
                if by_lang[lang]:
                    mixed.append(by_lang[lang].pop(0))
        pools[c] = mixed
    out: list[PlannedQuery] = []
    weight = sum(WEB_WEIGHTS.get(c, 0) for c in cats) or 1
    for c in cats:   # weighted quota per category
        quota = int(round(max_requests * WEB_WEIGHTS.get(c, 0) / weight))
        take, pools[c] = pools[c][:quota], pools[c][quota:]
        out += take
    while len(out) < max_requests and any(pools.values()):   # unused quota (small categories) goes to priority order
        for c in cats:
            if pools[c] and len(out) < max_requests:
                out.append(pools[c].pop(0))
                break
    return out[:max_requests]
