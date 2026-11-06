"""Evaluate the classifier on REAL, manually labelled records from live run 42174857442.

  python3 -m benchmark.run_real_eval --split dev       # tuning set
  python3 -m benchmark.run_real_eval --split heldout   # quality gate (never used for tuning; hash-locked)

Gold labels (written before the relevance filter existed):
  R relevant service opportunity · P product/licence/hardware only · N not relevant · U uncertain

Metrics
  Precision@k   share of the top-k ranked records that are gold R (strict) / R or P (lenient)
  FPR           gold non-R records placed in Priority A/B ÷ all gold non-R records
  Missed        gold R records NOT placed in Priority A/B (with the reason)
  The old classifier (as it ran in 42174857442) is reported on the same records as a baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from signal_engine import markets, validate
from signal_engine.models import Signal

HERE = Path(__file__).resolve().parent / "real_2026-11-06"
RUN_AT = datetime(2026, 11, 6, 6, 31, 45, tzinfo=timezone.utc)
_DEADLINE = re.compile(r"deadline (\S+)")
_NAME_TO_ISO3 = {n: v[1] for n, v in markets.COUNTRIES.items()}


def load(split: str) -> list[dict]:
    path = HERE / f"{split}.jsonl"
    if split == "heldout":
        lock = (HERE / "heldout.lock").read_text().strip()
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock:
            raise SystemExit("heldout.jsonl changed after it was frozen: refusing to evaluate.")
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def to_signal(it: dict) -> Signal:
    m = _DEADLINE.search(it["availability_basis"])
    meta = {"kind": "tender"}
    iso3 = _NAME_TO_ISO3.get(it["country"])
    if it["source"] == "ted" and iso3:
        meta["buyer_country_code"] = iso3
    return Signal(source=it["source"], source_id=it["id"], url=it["url"], title=it["title"],
                  text="" if it["excerpt"].startswith("unknown") else it["excerpt"],
                  verification_status="verified_api", posted_at=None if it["published_at"] == "unknown" else it["published_at"],
                  deadline_at=m.group(1) if m else None, organisation=None if it["organisation"] == "unknown" else it["organisation"],
                  country_hint="UK" if it["source"] in ("contracts_finder", "find_a_tender") else None, raw_meta=meta)


def evaluate(items: list[dict]) -> dict:
    gold = {it["url"]: it for it in items}
    recs, _, _ = validate.build_report([to_signal(it) for it in items], now=RUN_AT)
    ranked = [r for r in recs if r["verification_status"] == "verified_api"]
    actionable = [r for r in ranked if r["queue"] in ("PRIORITY_A", "PRIORITY_B")]

    def p_at(k, rows, ok=("R",)):
        top = rows[:k]
        return sum(gold[r["url"]]["gold_relevance"] in ok for r in top), len(top)

    non_r = [it for it in items if it["gold_relevance"] != "R"]
    fp = [r for r in actionable if gold[r["url"]]["gold_relevance"] != "R"]
    missed_all = [r for r in ranked if gold[r["url"]]["gold_relevance"] == "R" and r["queue"] not in ("PRIORITY_A", "PRIORITY_B")]
    # A gold-R record excluded only because its deadline passed / it was awarded is a correct exclusion, not a miss.
    stage_excluded = [r for r in missed_all if r["service_relevance"] == "relevant" and r["queue"] == "EXCLUDED"]
    missed = [r for r in missed_all if r not in stage_excluded]
    # Baseline: the old classifier's order as it ran (items are stored in that order)
    old_rank = sorted(items, key=lambda it: int(it["id"][1:]))
    old_act = [it for it in old_rank if it["old_classifier"]["queue"] in ("PRIORITY_A", "PRIORITY_B")]
    old_p = lambda k: (sum(it["gold_relevance"] == "R" for it in old_rank[:k]), min(k, len(old_rank)))
    conf = Counter((gold[r["url"]]["gold_relevance"], r["service_relevance"]) for r in ranked)
    return {
        "n": len(items), "gold": dict(Counter(it["gold_relevance"] for it in items)),
        "p@10": p_at(10, ranked), "p@20": p_at(20, ranked),
        "lead_p@10": p_at(10, actionable), "lead_p@20": p_at(20, actionable),
        "stage_excluded": [(gold[r["url"]]["id"], r["title"][:70], "; ".join(r["reasons"])[:80]) for r in stage_excluded],
        "p@10_lenient": p_at(10, ranked, ("R", "P")), "p@20_lenient": p_at(20, ranked, ("R", "P")),
        "actionable": len(actionable), "actionable_R": len(actionable) - len(fp),
        "fp": [(gold[r["url"]]["id"], gold[r["url"]]["gold_relevance"], r["title"][:80], r["service_relevance"]) for r in fp],
        "fpr": (len(fp), len(non_r)),
        "missed": [(gold[r["url"]]["id"], r["title"][:80], r["service_relevance"], r["queue"], "; ".join(r["reasons"])[:90]) for r in missed],
        "gold_R": sum(it["gold_relevance"] == "R" for it in items),
        "relevance_confusion": {f"{g}->{p}": n for (g, p), n in sorted(conf.items())},
        "top20": [(gold[r["url"]]["id"], gold[r["url"]]["gold_relevance"], r["queue"], r["service_relevance"], r["title"][:70]) for r in ranked[:20]],
        "old": {"p@10": old_p(10), "p@20": old_p(20), "actionable": len(old_act),
                "actionable_R": sum(it["gold_relevance"] == "R" for it in old_act),
                "fpr": (sum(it["gold_relevance"] != "R" for it in old_act), len(non_r))},
    }


def to_markdown(split: str, res: dict) -> str:
    f = lambda t: f"{t[0]}/{t[1]} ({100 * t[0] / t[1]:.0f}%)" if t[1] else "n/a"
    L = [f"# Real-record evaluation — {split} split", "",
         f"Records: {res['n']} (gold: {res['gold']}). Source: live run 42174857442, labelled manually before the relevance filter was written.", "",
         "| Metric | Old classifier (as run) | New classifier |", "|---|---|---|",
         f"| Precision@10 (strict, gold R) | {f(res['old']['p@10'])} | {f(res['p@10'])} |",
         f"| Precision@20 (strict, gold R) | {f(res['old']['p@20'])} | {f(res['p@20'])} |",
         f"| Precision of surfaced leads (Priority A/B), top 10 | — | {f(res['lead_p@10'])} |",
         f"| Precision of surfaced leads (Priority A/B), top 20 | — | {f(res['lead_p@20'])} |",
         f"| Precision@10 (lenient, R or P) | — | {f(res['p@10_lenient'])} |",
         f"| Precision@20 (lenient, R or P) | — | {f(res['p@20_lenient'])} |",
         f"| Priority A+B records | {res['old']['actionable']} ({res['old']['actionable_R']} gold R) | {res['actionable']} ({res['actionable_R']} gold R) |",
         f"| False-positive rate (non-R in A/B ÷ all non-R) | {f(res['old']['fpr'])} | {f(res['fpr'])} |",
         f"| Relevant records missed by relevance/queue errors | — | {len(res['missed'])} of {res['gold_R']} |",
         f"| Relevant but correctly excluded (closed / awarded) | — | {len(res['stage_excluded'])} |", "",
         "Note: full-ranking Precision@k is capped by the number of gold R records in the split (k > #R means < 100% even if perfect).", "",
         "## Top 20 (new ranking)", "", "| # | id | gold | queue | relevance | title |", "|---|---|---|---|---|---|"]
    for i, t in enumerate(res["top20"], 1):
        L.append(f"| {i} | {t[0]} | {t[1]} | {t[2]} | {t[3]} | {t[4].replace('|', '/')} |")
    L += ["", "## False positives in Priority A/B", ""] + [f"- {x}" for x in res["fp"]] or ["- none"]
    L += ["", "## Missed relevant records (relevance or queue error)", ""] + ([f"- {x}" for x in res["missed"]] or ["- none"])
    L += ["", "## Relevant but correctly excluded (closed / awarded)", ""] + ([f"- {x}" for x in res["stage_excluded"]] or ["- none"])
    L += ["", "## Relevance verdict vs gold", "", f"`{json.dumps(res['relevance_confusion'])}`", ""]
    return "\n".join(L)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=("dev", "heldout"), required=True)
    p.add_argument("--write", action="store_true")
    a = p.parse_args()
    res = evaluate(load(a.split))
    md = to_markdown(a.split, res)
    print(md)
    if a.write:
        (HERE / f"results_{a.split}.md").write_text(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
