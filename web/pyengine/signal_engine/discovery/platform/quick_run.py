"""'Run discovery' from the dashboard: a quick, bounded refresh executed by the website under the owner's own session.

Reads fresh client projects from the public boards (fewer queries, short polite delays), passes them through the same
ingest gate as the scheduled task, saves them with member_ingest_discovery (RLS: editors only), then re-checks the most
important saved board leads. Deep qualification and proposal drafts remain the scheduled Claude task's job.
Bounded so it finishes inside the website's 60-second function limit. Returns counts only.
"""
from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import agent_ingest, boards_reader

QUICK_FM_QUERIES = ["automatisierung", "n8n", "ki", "schnittstelle", "chatbot"]


def run(rpc_fn: Callable[[str, dict], object], days: int = 7, budget_s: float = 48.0, recheck_limit: int = 10) -> dict:
    t0 = time.monotonic()
    boards_reader.DELAY_S = 0.8
    jobs = {"freelancermap": lambda: boards_reader.freelancermap(days, queries=QUICK_FM_QUERIES),
            "codeur": lambda: boards_reader.codeur(days, pages=2),
            "peopleperhour": lambda: boards_reader.peopleperhour(days, pages=1),
            "airtable": lambda: boards_reader.airtable_jobs(days)}
    found, stats = [], {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs.items()}
        for name, fut in futures.items():
            try:
                got = fut.result(timeout=max(5.0, budget_s - 18 - (time.monotonic() - t0)))
                stats[name] = len(got)
                found += got
            except Exception as exc:   # one board failing never stops the others
                stats[name] = f"error: {type(exc).__name__}"
    cands = list({c["url"]: c for c in found}.values())
    items, rejected = agent_ingest.process(cands, verify=False)
    by_src = Counter(i["source_key"] for i in items)
    logs = [{"source_key": k, "status": "ok", "requests": 0, "records": n} for k, n in by_src.items()]
    saved = rpc_fn("member_ingest_discovery", {"p_run": {"logs": logs}, "p_items": items}) if items else {}
    rechecked = {}
    if time.monotonic() - t0 < budget_s - 12:
        try:
            rechecked = boards_reader.recheck(recheck_limit, rpc_fn=rpc_fn, delay=0.5)
        except Exception as exc:
            rechecked = {"error": type(exc).__name__}
    saved = saved if isinstance(saved, dict) else {}
    return {"boards": stats, "found": len(cands), "accepted": len(items), "rejected": sum(rejected.values()),
            "added": int(saved.get("added", 0)), "updated": int(saved.get("updated", 0)), "duplicates": int(saved.get("duplicates", 0)),
            "rechecked": rechecked.get("checked", 0), "closed_or_removed": (rechecked.get("database") or {}).get("closed_or_removed", 0),
            "seconds": round(time.monotonic() - t0, 1)}
