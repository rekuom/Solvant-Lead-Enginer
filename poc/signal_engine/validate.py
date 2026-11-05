"""Phase 2A live-validation CLI. Run from poc/.

  python3 -m signal_engine.validate probe                  # Task 1: access per domain/endpoint
  python3 -m signal_engine.validate verify                 # Task 2: re-fetch the 36 Phase 1 candidates
  python3 -m signal_engine.validate discover --days 30     # Task 2: new items from permitted sources
  python3 -m signal_engine.validate report                 # Tasks 3–5: qualify, review table, funnel
  python3 -m signal_engine.validate capture --url ... --title ... --excerpt ... --posted-at ... --reviewer ...
  python3 -m signal_engine.validate all --days 30          # probe + verify + discover + report

All output goes to poc/out/validation/ (git-ignored). Nothing is written to any database.
Every fetch failure is logged with its kind (proxy_block vs source refusal etc.).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import probe as probe_mod
from .classify import classify
from .collectors import discourse, ocds, search_candidates
from .collectors.http import FetchBlocked, PoliteClient
from .dedupe import dedupe
from .models import Signal
from .qualify import qualify
from .textutil import make_excerpt

OUT = Path("out/validation")
CANDIDATE_GLOB = "data/search_candidates_*.json"

# Single-notice JSON endpoints for tenders are NOT confirmed by documentation; tried in order,
# and whichever answers is recorded so the next run can rely on it.
CF_SINGLE = ["https://www.contractsfinder.service.gov.uk/Published/Notice/OCDS/{guid}"]
FTS_SINGLE = ["https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages/{nid}"]
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_FTS = re.compile(r"(\d{6}-\d{4})")
_TOPIC_ID = re.compile(r"/t/(?:[^/]+/)?(\d+)")


def load_candidates() -> list[Signal]:
    out: list[Signal] = []
    for f in sorted(Path(".").glob(CANDIDATE_GLOB)):
        out += search_candidates.load(f)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def _sig_from_dict(d: dict) -> Signal:
    return Signal(**d)


# --------------------------------------------------------------------------- probe
def cmd_probe(days: int) -> list[dict]:
    since = (_now() - timedelta(days=days)).date().isoformat()
    results = probe_mod.run_probe(since)
    rows = probe_mod.results_to_json(results)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "probe.json").write_text(json.dumps(rows, indent=2))
    (OUT / "probe.md").write_text(probe_mod.to_markdown(results, _now().isoformat()))
    print(probe_mod.to_markdown(results, _now().isoformat()))
    return rows


# --------------------------------------------------------------------------- verify
def verify_one(client: PoliteClient, cand: Signal) -> tuple[Optional[Signal], dict]:
    log = {"url": cand.url, "source": cand.source, "result": None, "kind": None, "endpoint": None}
    try:
        if cand.source.startswith("discourse:"):
            host = cand.source.split(":", 1)[1]
            m = _TOPIC_ID.search(cand.url)
            if not m:
                log.update(result="skipped", kind="no_topic_id")
                return None, log
            ep = f"https://{host}/t/{m.group(1)}.json"
            log["endpoint"] = ep
            sig = discourse.parse_topic(host, client.get_json(ep))
        elif cand.source in ("contracts_finder", "find_a_tender"):
            if cand.source == "contracts_finder":
                key = _GUID.search(cand.url); tmpl = CF_SINGLE; fill = {"guid": key.group(0).lower() if key else ""}
            else:
                key = _FTS.search(cand.url); tmpl = FTS_SINGLE; fill = {"nid": key.group(1) if key else ""}
            if not key:
                log.update(result="skipped", kind="no_notice_id")
                return None, log
            sig, last_exc = None, None
            for t in tmpl:
                ep = t.format(**fill)
                log["endpoint"] = ep
                try:
                    pkg = client.get_json(ep, check_robots=False)
                except FetchBlocked as exc:
                    last_exc = exc
                    continue
                if "releases" not in pkg and "ocid" in pkg:
                    pkg = {"releases": [pkg]}
                parsed = ocds.parse_release_package(pkg, cand.source)
                sig = parsed[-1] if parsed else None  # latest release for the notice
                break
            if sig is None and last_exc is not None:
                raise last_exc
        else:
            log.update(result="skipped", kind="unsupported_source")
            return None, log
    except FetchBlocked as exc:
        log.update(result="failed", kind=exc.kind, error=str(exc)[:300])
        return None, log
    if sig is None:
        log.update(result="failed", kind="empty_or_unparseable")
        return None, log
    log.update(result="verified", kind="ok", posted_at=sig.posted_at)
    return sig, log


def cmd_verify(client: Optional[PoliteClient] = None) -> tuple[list[Signal], list[dict]]:
    client = client or PoliteClient(min_interval_s=3.0)
    cands = load_candidates()
    verified, logs = [], []
    for c in cands:
        sig, log = verify_one(client, c)
        logs.append(log)
        if sig:
            verified.append(sig)
    _write_jsonl(OUT / "verify_log.jsonl", logs)
    _write_jsonl(OUT / "verified.jsonl", [s.to_dict() for s in verified])
    print(f"verify: {len(verified)}/{len(cands)} verified; failures by kind: "
          f"{dict(Counter(l['kind'] for l in logs if l['result'] != 'verified'))}")
    return verified, logs


# --------------------------------------------------------------------------- discover
def cmd_discover(days: int, client: Optional[PoliteClient] = None, max_topics: int = 40) -> tuple[list[Signal], list[dict]]:
    client = client or PoliteClient(min_interval_s=3.0)
    since_dt = _now() - timedelta(days=days)
    since = since_dt.date().isoformat()
    found: list[Signal] = []
    logs: list[dict] = []

    def run(name, fn):
        try:
            got = fn()
            found.extend(got)
            logs.append({"source": name, "result": "ok", "items": len(got)})
        except FetchBlocked as exc:
            logs.append({"source": name, "result": "failed", "kind": exc.kind, "error": str(exc)[:300]})

    run("contracts_finder", lambda: ocds.fetch_contracts_finder(client, since, _now().date().isoformat()))
    run("find_a_tender", lambda: ocds.fetch_find_a_tender(client, f"{since}T00:00:00"))
    for host in discourse.FORUMS:
        run(f"discourse:{host}", lambda h=host: discourse.fetch_forum(client, h, max_topics=max_topics, since=since_dt))
    _write_jsonl(OUT / "discover_log.jsonl", logs)
    _write_jsonl(OUT / "discovered.jsonl", [s.to_dict() for s in found])
    print(f"discover: {len(found)} items; {logs}")
    return found, logs


# --------------------------------------------------------------------------- capture (human-assisted)
def cmd_capture(a: argparse.Namespace) -> dict:
    sig = Signal(source=a.source, source_id=a.url, url=a.url, title=a.title, text=make_excerpt(a.excerpt),
                 verification_status="human_verified", posted_at=a.posted_at, collected_at=_now().isoformat(),
                 raw_meta={"kind": "human_capture", "reviewer": a.reviewer})
    path = OUT / "human_captures.jsonl"
    rows = _read_jsonl(path) + [sig.to_dict()]
    _write_jsonl(path, rows)
    c = classify(sig)
    q = qualify(sig, c)
    print(json.dumps({"intent_tier": c.intent_tier, "qualification": q.qualification, "reasons": q.reasons}, indent=2))
    return q.to_dict()


# --------------------------------------------------------------------------- report
ACTION = {
    "QUALIFIED": "Contact via the source's permitted route within 48h",
    "NEEDS_REVIEW": "Human check: open URL, confirm location/date/status, then decide",
    "EXCLUDED": "Do not contact",
}


def build_report(signals: list[Signal], now: Optional[datetime] = None, probe_rows: Optional[list[dict]] = None,
                 logs: Optional[dict] = None) -> tuple[list[dict], dict, str]:
    now = now or _now()
    kept, dropped = dedupe(signals)
    recs = []
    for s in kept:
        c = classify(s, now=now)
        q = qualify(s, c, now=now)
        recs.append({**q.to_dict(), "score": c.score, "classifier_reasons": c.reasons})
    genuine = [r for r in recs if r["verification_status"] in ("verified_api", "human_verified")]
    fresh_ukuae = [r for r in genuine if r["age_days"] is not None and r["age_days"] <= 30 and r["country"] in ("UK", "UAE")]
    seeking = [r for r in fresh_ukuae if r["intent_tier"] in ("A", "B")]
    budget_ok = [r for r in seeking if r["budget_fit"] in ("fit", "stretch", "unknown") and r["deliverable"] != "no"]
    contactable = [r for r in budget_ok if r["contact_permitted"] and r["availability"] != "closed"]
    qualified = [r for r in recs if r["qualification"] == "QUALIFIED"]
    high_intent = [r for r in genuine if r["intent_tier"] in ("A", "B")]
    funnel = {
        "run_at": now.isoformat(),
        "records_total": len(recs), "duplicates_dropped": len(dropped),
        "by_verification": dict(Counter(r["verification_status"] for r in recs)),
        "genuine_records": len(genuine),
        "1_verified_uk_uae_last_30d": len(fresh_ukuae),
        "2_seeking_external_provider": len(seeking),
        "3_relevant_to_1k_3k": len(budget_ok),
        "4_permitted_practical_contact_route": len(contactable),
        "qualified": len(qualified),
        "high_intent_genuine_reviewed": len(high_intent),
        "by_qualification": dict(Counter(r["qualification"] for r in recs)),
        "exclusion_reasons": dict(Counter(x for r in recs for x in r["reasons"])),
        "false_positives": "requires human verdicts — see benchmark/heldout",
    }
    md = ["# Phase 2A lead review", "", f"Run: {now.isoformat()}", "", "## Funnel", "", "| Step | Count |", "|---|---|"]
    for k in ("records_total", "genuine_records", "1_verified_uk_uae_last_30d", "2_seeking_external_provider",
              "3_relevant_to_1k_3k", "4_permitted_practical_contact_route", "qualified"):
        md.append(f"| {k} | {funnel[k]} |")
    md += ["", "## High-intent items (Tier A/B, any verification status)", "",
           "| Buyer / company | Country | Business problem | Date | Evidence URL | Intent tier | Commercial fit | Confidence | Recommended action |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(recs, key=lambda r: (-r["score"])):
        if r["intent_tier"] not in ("A", "B"):
            continue
        conf = "high" if r["verification_status"] in ("verified_api", "human_verified") and r["qualification"] == "QUALIFIED" \
            else "medium" if r["verification_status"] in ("verified_api", "human_verified") else "low (title only)"
        fit = f"{r['budget_fit']}; deliverable={r['deliverable']}; availability={r['availability']}"
        problem = (r["buyer_request"] if not r["buyer_request"].startswith("unknown") else r["title"])[:110].replace("|", "/")
        md.append(f"| {r['organisation']} | {r['country']} | {problem} | {r['published_at'][:10]} | {r['url']} | "
                  f"{r['intent_tier']} | {fit} | {conf} | {ACTION[r['qualification']]}"
                  f"{'' if r['qualification'] != 'EXCLUDED' else ' (' + '; '.join(r['reasons'])[:80] + ')'} |")
    if probe_rows:
        md += ["", "## Access probe summary", ""]
        for row in probe_rows:
            md.append(f"- {row['domain']} {row['name']}: **{row['kind']}** (status {row['status']}, blocked by {row['blocked_by']})")
    if logs:
        md += ["", "## Fetch logs", "", "```", json.dumps(logs, indent=1, default=str)[:4000], "```"]
    return recs, funnel, "\n".join(md) + "\n"


def cmd_report(include_candidates: bool = True) -> dict:
    signals = [_sig_from_dict(d) for d in _read_jsonl(OUT / "verified.jsonl")]
    signals += [_sig_from_dict(d) for d in _read_jsonl(OUT / "discovered.jsonl")]
    signals += [_sig_from_dict(d) for d in _read_jsonl(OUT / "human_captures.jsonl")]
    verified_urls = {s.url for s in signals}
    if include_candidates:  # unverified ones stay visible, but can never qualify
        signals += [c for c in load_candidates() if c.url not in verified_urls]
    probe_rows = json.loads((OUT / "probe.json").read_text()) if (OUT / "probe.json").exists() else None
    logs = {"verify": _read_jsonl(OUT / "verify_log.jsonl"), "discover": _read_jsonl(OUT / "discover_log.jsonl")}
    recs, funnel, md = build_report(signals, probe_rows=probe_rows, logs=logs)
    _write_jsonl(OUT / "leads.jsonl", recs)
    (OUT / "funnel.json").write_text(json.dumps(funnel, indent=2))
    (OUT / "lead_review.md").write_text(md)
    print(json.dumps(funnel, indent=2))
    return funnel


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("probe", "discover", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("--days", type=int, default=30)
    sub.add_parser("verify")
    sub.add_parser("report")
    cp = sub.add_parser("capture")
    for f in ("url", "title", "excerpt", "posted-at", "reviewer"):
        cp.add_argument(f"--{f}", required=True)
    cp.add_argument("--source", default="human:other")
    a = p.parse_args(argv)
    if a.cmd == "probe":
        cmd_probe(a.days)
    elif a.cmd == "verify":
        cmd_verify()
    elif a.cmd == "discover":
        cmd_discover(a.days)
    elif a.cmd == "report":
        cmd_report()
    elif a.cmd == "capture":
        cmd_capture(a)
    elif a.cmd == "all":
        cmd_probe(a.days)
        cmd_verify()
        cmd_discover(a.days)
        cmd_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
