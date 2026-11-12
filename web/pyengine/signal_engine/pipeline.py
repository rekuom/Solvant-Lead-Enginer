"""Collection pipeline: collect -> dedupe -> classify -> write JSONL + summary.

Usage (from repo root):
  python -m signal_engine.pipeline --candidates data/search_candidates_2026-11-05.json
  python -m signal_engine.pipeline --fixtures fixtures               # synthetic parser fixtures
  python -m signal_engine.pipeline --live contracts_finder,find_a_tender --since 2026-10-06
Run from the poc/ directory. Output goes to poc/out/ (git-ignored). Nothing is written to any database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .classify import classify
from .collectors import discourse, ocds, search_candidates
from .collectors.http import FetchBlocked, PoliteClient
from .dedupe import dedupe
from .models import Signal


def load_fixtures(folder: Path) -> list[Signal]:
    sigs: list[Signal] = []
    for f in sorted(folder.glob("*.json")):
        data = json.loads(f.read_text())
        status = "synthetic" if data.get("_synthetic") else "verified_api"
        kind = data.get("_kind")
        if kind == "ocds":
            sigs += ocds.parse_release_package(data["package"], data["_source"], verification_status=status)
        elif kind == "discourse_topic":
            s = discourse.parse_topic(data["_host"], data["topic"], verification_status=status)
            if s:
                sigs.append(s)
    return sigs


def collect_live(sources: list[str], since: str, log: list[str]) -> list[Signal]:
    client = PoliteClient()
    out: list[Signal] = []
    today = datetime.now(timezone.utc).date().isoformat()
    for src in sources:
        try:
            if src == "contracts_finder":
                out += ocds.fetch_contracts_finder(client, since, today)
            elif src == "find_a_tender":
                out += ocds.fetch_find_a_tender(client, f"{since}T00:00:00")
            elif src.startswith("discourse:"):
                out += discourse.fetch_forum(client, src.split(":", 1)[1])
            else:
                log.append(f"{src}: unknown source")
                continue
            log.append(f"{src}: ok")
        except FetchBlocked as exc:
            log.append(f"{src}: BLOCKED — {exc}")
    return out


def run(signals: list[Signal], out_dir: Path, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    kept, dropped = dedupe(signals)
    rows = []
    for s in kept:
        c = classify(s, now=now)
        rows.append({"signal": s.to_dict(), "classification": c.to_dict()})
    rows.sort(key=lambda r: -r["classification"]["score"])

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "signals.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "run_at": now.isoformat(),
        "input_records": len(signals),
        "after_dedupe": len(kept),
        "duplicates_dropped": dropped,
        "genuine_verified_signals": sum(1 for s in kept if s.is_genuine),
        "by_verification": dict(Counter(s.verification_status for s in kept)),
        "by_intent_tier": dict(Counter(r["classification"]["intent_tier"] for r in rows)),
        "by_actionable": dict(Counter(r["classification"]["actionable"] for r in rows)),
        "reject_reasons": dict(Counter(r["classification"]["reject_reason"] for r in rows if r["classification"]["reject_reason"])),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def _print_table(out_dir: Path) -> None:
    for line in (out_dir / "signals.jsonl").read_text().splitlines():
        r = json.loads(line)
        s, c = r["signal"], r["classification"]
        print(f"{c['intent_tier']:>6} {c['actionable']:>11} {c['score']:>3}  {s['title'][:70]:<70}  {s['url']}")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--candidates", type=Path, action="append", default=[], help="search-candidate JSON file(s)")
    p.add_argument("--fixtures", type=Path, help="folder of fixture JSON files")
    p.add_argument("--live", help="comma list: contracts_finder,find_a_tender,discourse:community.n8n.io")
    p.add_argument("--since", default=(datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat())
    p.add_argument("--out", type=Path, default=Path("out"))
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    signals: list[Signal] = []
    for c in a.candidates:
        signals += search_candidates.load(c)
    if a.fixtures:
        signals += load_fixtures(a.fixtures)
    log: list[str] = []
    if a.live:
        signals += collect_live([x.strip() for x in a.live.split(",") if x.strip()], a.since, log)
    if not signals:
        print("No input signals.", "; ".join(log), file=sys.stderr)
        return 1
    summary = run(signals, a.out)
    summary["live_log"] = log
    if not a.quiet:
        _print_table(a.out)
    print(json.dumps({k: v for k, v in summary.items() if k != "duplicates_dropped"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
