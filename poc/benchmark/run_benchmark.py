"""Benchmark the intent classifier against manual gold labels.

Run from poc/:  python -m benchmark.run_benchmark [--label v1] [--write]
Writes benchmark/results_<label>.md when --write is given.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from signal_engine.classify import classify
from signal_engine.collectors import search_candidates
from signal_engine.models import Signal

HERE = Path(__file__).resolve().parent
ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "REJECT": 4}
ACTIONABLE = {"A", "B"}


def load_items() -> list[dict]:
    gold = json.loads((HERE / "gold_labels.json").read_text())
    cands = {s.url: s for s in search_candidates.load(HERE.parent / "data" / "search_candidates_2026-11-05.json")}
    items = []
    for g in gold["real"]:
        items.append({"origin": "real", "signal": cands[g["url"]], "gold": g["gold"], "note": g.get("note", "")})
    for g in gold["synthetic"]:
        sig = Signal(source="benchmark", source_id=g["id"], url=f"https://example.invalid/{g['id']}",
                     title=g["title"], text="", verification_status="synthetic")
        items.append({"origin": "synthetic", "signal": sig, "gold": g["gold"], "note": g.get("note", "")})
    return items


def evaluate(items: list[dict]) -> dict:
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    rows = []
    for it in items:
        c = classify(it["signal"], now=now)
        rows.append({**it, "pred": c.intent_tier, "evidence": [e.matched for e in c.evidence], "reasons": c.reasons})
    scored = [r for r in rows if r["gold"] != "UNCLEAR"]
    exact = sum(r["pred"] == r["gold"] for r in scored)
    within1 = sum(abs(ORDER[r["pred"]] - ORDER[r["gold"]]) <= 1 for r in scored)
    pred_act = [r for r in scored if r["pred"] in ACTIONABLE]
    gold_act = [r for r in scored if r["gold"] in ACTIONABLE]
    tp = [r for r in pred_act if r["gold"] in ACTIONABLE]
    fp = [r for r in pred_act if r["gold"] not in ACTIONABLE]
    fn = [r for r in gold_act if r["pred"] not in ACTIONABLE]
    over = [r for r in scored if ORDER[r["pred"]] < ORDER[r["gold"]]]
    under = [r for r in scored if ORDER[r["pred"]] > ORDER[r["gold"]]]
    by_origin = {}
    for o in ("real", "synthetic"):
        sub = [r for r in scored if r["origin"] == o]
        by_origin[o] = {"n": len(sub), "exact": sum(r["pred"] == r["gold"] for r in sub)}
    return {
        "rows": rows, "n_total": len(rows), "n_scored": len(scored), "n_unclear": len(rows) - len(scored),
        "exact": exact, "within1": within1,
        "actionable_precision": (len(tp) / len(pred_act)) if pred_act else None,
        "actionable_recall": (len(tp) / len(gold_act)) if gold_act else None,
        "fp": fp, "fn": fn, "over": over, "under": under, "by_origin": by_origin,
        "confusion": Counter((r["gold"], r["pred"]) for r in scored),
    }


def to_markdown(res: dict, label: str) -> str:
    pct = lambda a, b: f"{a}/{b} ({100*a/b:.0f}%)" if b else "n/a"
    L = [f"# Benchmark results — classifier {label}", "",
         f"Items: {res['n_total']} ({res['n_unclear']} UNCLEAR excluded from scoring).", "",
         "| Metric | Value |", "|---|---|",
         f"| Exact tier accuracy | {pct(res['exact'], res['n_scored'])} |",
         f"| Within one tier | {pct(res['within1'], res['n_scored'])} |",
         f"| Real items exact | {pct(res['by_origin']['real']['exact'], res['by_origin']['real']['n'])} |",
         f"| Synthetic items exact | {pct(res['by_origin']['synthetic']['exact'], res['by_origin']['synthetic']['n'])} |",
         f"| Actionable (A/B) precision | {res['actionable_precision']:.2f} |" if res['actionable_precision'] is not None else "| Actionable precision | n/a |",
         f"| Actionable (A/B) recall | {res['actionable_recall']:.2f} |" if res['actionable_recall'] is not None else "| Actionable recall | n/a |",
         f"| False positives (pred A/B, gold C/D/REJECT) | {len(res['fp'])} |",
         f"| False negatives (gold A/B, pred C/D/REJECT) | {len(res['fn'])} |",
         f"| Over-scored (pred tier higher than gold) | {len(res['over'])} |",
         f"| Under-scored (pred tier lower than gold) | {len(res['under'])} |", "",
         "## Confusion matrix (rows = gold, cols = predicted)", "",
         "| gold \\ pred | A | B | C | D | REJECT |", "|---|---|---|---|---|---|"]
    for g in ORDER:
        L.append(f"| {g} | " + " | ".join(str(res["confusion"].get((g, p), 0)) for p in ORDER) + " |")
    L += ["", "## Every disagreement", "", "| origin | gold | pred | title | matched evidence | gold note |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        if r["gold"] != "UNCLEAR" and r["pred"] != r["gold"]:
            ev = "; ".join(r["evidence"])[:90].replace("|", "/")
            L.append(f"| {r['origin']} | {r['gold']} | {r['pred']} | {r['signal'].title[:80].replace('|', '/')} | {ev} | {r['note'].replace('|', '/')} |")
    L += ["", "## UNCLEAR items (not scored)", ""]
    for r in res["rows"]:
        if r["gold"] == "UNCLEAR":
            L.append(f"- pred **{r['pred']}** — {r['signal'].title} — {r['note']}")
    return "\n".join(L) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--label", default="current")
    p.add_argument("--write", action="store_true")
    a = p.parse_args()
    res = evaluate(load_items())
    md = to_markdown(res, a.label)
    print(md)
    if a.write:
        (HERE / f"results_{a.label}.md").write_text(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
