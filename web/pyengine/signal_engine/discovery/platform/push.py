"""Push a discovery run into the private Supabase database (used by GitHub Actions; public logs: COUNTS ONLY).

  python -m signal_engine.discovery.platform.push            # needs SIGNAL_INGEST_TOKEN, SUPABASE_URL, SUPABASE_ANON_KEY

Reads poc/out/discovery/raw_discovered.jsonl (+ run_log.json), classifies with the same engine as the report, and sends
original-source records only (Brave snippets never exist on disk; fixtures are never sent). Exit 0 when not configured.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import run as runmod
from .items import to_item
from .rest import RestError, rpc

BATCH = 500


def build_payload(out: Path) -> tuple[dict, list[dict]]:
    raw = [r for r in runmod._read_raw(out / "raw_discovered.jsonl") if r.source_key != "web_search_brave" and r.verification != "fixture"]
    opps, _ = runmod.build_opportunities(raw)
    items = [to_item(o) for o in opps]
    log = json.loads((out / "run_log.json").read_text()) if (out / "run_log.json").exists() else {"logs": []}
    logs = []
    for l in log.get("logs", []):
        key = {"search:brave": "web_search_brave", "rss_atom": "rss_atom", "landing_verification": None}.get(l["source"], l["source"])
        if key:
            logs.append({"source_key": key, "status": l.get("status"), "requests": l.get("requests", 0), "records": l.get("records", 0),
                         "failed": l.get("failed", 0), "est_cost_usd": l.get("est_cost_usd", 0),
                         "error_kind": next((e.get("error_kind") for e in l.get("events", []) if e.get("error_kind")), None),
                         "counts": {k: v for k, v in (log.get("brave_aggregate") or {}).items() if key == "web_search_brave" and isinstance(v, (int, dict))}})
    run = {"scope": "discovery", "external_run_id": os.environ.get("GITHUB_RUN_ID"), "started_at": log.get("run_at"), "logs": logs}
    return run, items


def main() -> int:
    token = os.environ.get("SIGNAL_INGEST_TOKEN", "")
    if not token:
        print("platform push: SIGNAL_INGEST_TOKEN not configured — skipped (nothing sent)")
        return 0
    run, items = build_payload(runmod.OUT)
    totals = {"added": 0, "updated": 0, "duplicates": 0, "rejected": 0}
    try:
        for i in range(0, max(1, len(items)), BATCH):
            res = rpc("ingest_records", {"p_token": token, "p_run": run if i == 0 else {"scope": "discovery"}, "p_items": items[i:i + BATCH]})
            for k in totals:
                totals[k] += int((res or {}).get(k, 0))
    except RestError as exc:
        print(f"platform push FAILED: HTTP {exc.status}")   # no payload echoed
        return 3
    print(f"platform push: {len(items)} records sent at {datetime.now(timezone.utc).isoformat()} -> " + json.dumps(totals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
