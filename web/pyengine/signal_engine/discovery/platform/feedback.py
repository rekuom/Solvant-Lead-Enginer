"""Print discovery feedback (last N days, counts only) so the scheduled task can re-weight queries, strategies and sources.

Queries are recorded as "<strategy>: <query text>" (e.g. "biz-accounting: can anyone recommend …", "de: suche Freelancer …",
"codeur: project list"). This report rolls them up by strategy and proposes today's search allocation: each search strategy
gets searches in proportion to its smoothed qualified-rate (Laplace: (qualified + 1) / (total + 2)), with at least one
exploratory search for every strategy so new or unlucky ones are still tested.

  python -m signal_engine.discovery.platform.feedback [--days 30] [--budget 20] [--json]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Optional

from .rest import RestError, rpc

COLS = ("total", "qualified", "priority_a", "employment", "not_qualified", "verified", "progressed_by_human", "corrected_by_human", "won")
# strategies fed by readers (not WebSearch): always run, so they take no share of the search budget
FEEDS = {"forum", "codeur", "freelancermap", "peopleperhour", "airtable community", "freelancer api", "theirstack", "email alert"}
SEARCH_STRATEGIES = ["biz-ecommerce", "biz-accounting", "biz-property", "biz-hospitality", "biz-recruitment", "biz-services",
                     "founder", "social", "board-search", "tech-forum", "github", "de", "fr", "es", "nl", "it", "uae"]


def strategy_of(key: str) -> str:
    k = str(key or "").strip().lower()
    if k.startswith("forum"):           # forum_reader leads ("forum feed …", "forum: …")
        return "forum"
    if ":" in k:
        return k.split(":", 1)[0].strip() or "(none)"
    return "(untagged)"


def rollup(rows: list[dict], searches: Optional[list[dict]] = None) -> list[dict]:
    """Per strategy: outcome counts, plus searches run (from the search log). The rate is qualified leads per attempt, where an
    attempt is a logged search (or a lead, for reader feeds and older untagged runs), smoothed: (qualified + 1) / (attempts + 2)."""
    agg: dict[str, dict] = defaultdict(lambda: {c: 0 for c in COLS})
    runs = {str(s.get("key") or "").lower(): int(s.get("searches") or 0) for s in (searches or [])}
    for k in runs:
        agg[k]
    for r in rows:
        a = agg[strategy_of(r.get("key"))]
        for c in COLS:
            a[c] += int(r.get(c) or 0)
    out = []
    for k, a in agg.items():
        attempts = max(a["total"], runs.get(k, 0))
        a = dict(a, key=k, searches=runs.get(k, 0), rate=round((a["qualified"] + 1) / (attempts + 2), 3))
        out.append(a)
    return sorted(out, key=lambda a: (-a["rate"], -a["qualified"]))


def allocate(strategies: list[dict], budget: int = 20, known: list[str] = SEARCH_STRATEGIES) -> dict[str, int]:
    """Searches per strategy: one exploratory each (as budget allows), the rest by smoothed qualified-rate."""
    rate = {s["key"]: s["rate"] for s in strategies if s["key"] not in FEEDS and s["key"] not in ("(none)", "(untagged)")}
    for k in known:
        rate.setdefault(k, 0.5)       # untested strategies start at the uninformed prior
    keys = sorted(rate, key=lambda k: -rate[k])
    plan = {k: 0 for k in keys}
    for k in keys[:budget]:
        plan[k] = 1
    left = budget - sum(plan.values())
    total = sum(rate.values()) or 1.0
    shares = sorted(((rate[k] / total * left, k) for k in keys), reverse=True)
    for share, k in shares:
        plan[k] += int(share)
    left = budget - sum(plan.values())
    for _, k in shares[:max(0, left)]:
        plan[k] += 1
    return {k: v for k, v in sorted(plan.items(), key=lambda kv: -kv[1]) if v}


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 30
    budget = int(argv[argv.index("--budget") + 1]) if "--budget" in argv else 20
    try:
        fb = rpc("discovery_feedback", {"p_token": "", "p_days": days}) or {}
    except RestError as exc:
        print(f"feedback unavailable: HTTP {exc.status}")
        return 3
    strategies = rollup(fb.get("by_query", []), fb.get("by_strategy_searches", []))
    plan = allocate(strategies, budget)
    if "--json" in argv:
        print(json.dumps({"by_strategy": strategies, "search_plan": plan, "by_source": fb.get("by_source", [])}))
        return 0
    cols = COLS + ("searches", "rate")
    for dim, rows in (("by_strategy", strategies), ("by_source", fb.get("by_source", [])), ("by_query", fb.get("by_query", []))):
        print(f"\n{dim} (last {days} days)\n" + "key".ljust(48) + " ".join(c[:9].rjust(9) for c in cols))
        for r in rows:
            print(str(r.get("key"))[:47].ljust(48) + " ".join(str(r.get(c, "")).rjust(9) for c in cols))
    print(f"\nToday's search plan ({budget} searches): " + ", ".join(f"{k} {v}" for k, v in plan.items()))
    print("Use: follow the plan; within a strategy repeat/vary queries with qualified > 0 (especially progressed_by_human or won);"
          " drop queries with total >= 5 and qualified == 0; treat corrected_by_human as a quality warning.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
