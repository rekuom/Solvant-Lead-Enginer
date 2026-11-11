"""Live-validation CLI. Run from poc/.

  python3 -m signal_engine.validate live --days 30 --max-records 100   # discover + verify + report (permitted sources only)
  python3 -m signal_engine.validate probe                              # access probe (no collection)
  python3 -m signal_engine.validate permissions                        # print the source-permission registry
  python3 -m signal_engine.validate discover --days 30
  python3 -m signal_engine.validate verify
  python3 -m signal_engine.validate report
  python3 -m signal_engine.validate capture --url ... --title ... --excerpt ... --posted-at ... --reviewer ...

Rules enforced here:
  * A collector runs only if signal_engine/sources.py marks collection as permitted.
  * Search-index candidates are re-fetched only from permitted sources; otherwise they stay UNVERIFIED.
  * At most --max-records genuine records are kept (most actionable first); each source has a request cap.
  * Output goes to poc/out/validation/ (git-ignored). Nothing is written to any database. No outreach.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from . import probe as probe_mod
from . import sources
from .classify import classify
from .collectors import discourse, ocds, search_candidates, ted
from .collectors.http import FetchBlocked, PoliteClient
from .dedupe import dedupe
from .models import Signal
from .qualify import (EXCLUDED, PRIORITY_A, PRIORITY_B, PRIORITY_C, QUEUE_ORDER, REVIEW, UNVERIFIED, WATCHLIST, qualify)
from .textutil import make_excerpt

OUT = Path("out/validation")
CANDIDATE_GLOB = "data/search_candidates_*.json"

# Contracts Finder has no confirmed single-notice OCDS endpoint: the guessed one returned 404 for every candidate
# in run 42174857442, so CF candidates are not re-fetched (they stay UNVERIFIED unless the collector finds them).
CF_SINGLE: list[str] = []
FTS_SINGLE = ["https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages/{nid}"]
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_FTS = re.compile(r"(\d{6}-\d{4})")
_TOPIC_ID = re.compile(r"/t/(?:[^/]+/)?(\d+)")

CSV_COLUMNS = [
    "queue", "score", "intent_tier", "title", "organisation", "country", "market", "location_evidence",
    "published_at", "age_days", "url", "business_requirement", "external_provider_evidence", "budget_stated",
    "budget_kind", "budget_gbp_estimate", "availability", "availability_basis", "contact_route", "potential_service",
    "complexity", "delivery_flags", "partnership_opportunity", "risk_flags", "missing_details", "reasons",
    "classification_evidence", "source", "verification_status", "source_collection_permitted",
    "service_relevance", "deliverable_type", "relevance_evidence", "relevance_against", "relevance_uncertainty",
    "opportunity_kind", "procurement_stage", "delivery_mode",
]
_REL_ORDER = {"relevant": 0, "uncertain": 1, "product_only": 2, "unknown": 3, "not_relevant": 4}
QUEUE_TITLES = {
    PRIORITY_A: "Priority A — Immediate opportunities",
    PRIORITY_B: "Priority B — Promising opportunities",
    PRIORITY_C: "Priority C — Potential prospects",
    REVIEW: "Review — service relevance uncertain (human decision needed)",
    WATCHLIST: "Watchlist — weak signals, product/licence purchases (lower priority)",
    EXCLUDED: "Excluded",
    UNVERIFIED: "Unverified — search-index titles (not counted)",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_candidates() -> list[Signal]:
    out: list[Signal] = []
    for f in sorted(Path(".").glob(CANDIDATE_GLOB)):
        out += search_candidates.load(f)
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


# --------------------------------------------------------------------------- probe / permissions
def cmd_probe(days: int, timeout: float = 30) -> list[dict]:
    since = (_now() - timedelta(days=days)).date().isoformat()
    results = probe_mod.run_probe(since, timeout=timeout)
    rows = probe_mod.results_to_json(results)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "probe.json").write_text(json.dumps(rows, indent=2))
    (OUT / "probe.md").write_text(probe_mod.to_markdown(results, _now().isoformat()))
    print(probe_mod.to_markdown(results, _now().isoformat()))
    return rows


def permissions_markdown() -> str:
    L = ["| Source | Automated collection | Basis | Blocker | Checked |", "|---|---|---|---|---|"]
    for p in sources.SOURCES.values():
        L.append(f"| {p.name} (`{p.key}`) | {'**PERMITTED — enabled**' if p.collection_permitted else '**BLOCKED — disabled**'} | "
                 f"{p.basis} | {p.blocker or '—'} | {p.checked_on} |")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- verify
def verify_one(client: PoliteClient, cand: Signal) -> tuple[Optional[Signal], dict]:
    log = {"url": cand.url, "source": cand.source, "result": None, "kind": None, "endpoint": None}
    if not sources.permitted(cand.source):
        log.update(result="skipped", kind="permission_not_obtained", blocker=sources.policy(cand.source).blocker)
        return None, log
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
            if not tmpl:
                log.update(result="skipped", kind="no_single_notice_api")
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
                sig = parsed[-1] if parsed else None
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
    print(f"verify: {len(verified)}/{len(cands)} verified; not verified by kind: "
          f"{dict(Counter(l['kind'] for l in logs if l['result'] != 'verified'))}")
    return verified, logs


# --------------------------------------------------------------------------- discover
def collector_plan(client: PoliteClient, since_dt: datetime, ted_log: list) -> dict[str, Callable[[], list[Signal]]]:
    since = since_dt.date().isoformat()
    today = _now().date().isoformat()
    plan: dict[str, Callable[[], list[Signal]]] = {
        "contracts_finder": lambda: ocds.fetch_contracts_finder(
            client, since, today, max_pages=sources.policy("contracts_finder").max_requests_per_run, log=ted_log),
        "find_a_tender": lambda: ocds.fetch_find_a_tender(
            client, f"{since}T00:00:00", max_pages=sources.policy("find_a_tender").max_requests_per_run),
        "ted": lambda: ted.fetch_ted(client, since_dt, limit=50, max_pages=sources.policy("ted").max_requests_per_run,
                                     log=ted_log),
    }
    for host in discourse.FORUMS:
        plan[f"discourse:{host}"] = (lambda h=host: discourse.fetch_forum(client, h, max_topics=40, since=since_dt))
    return plan


def cmd_discover(days: int, client: Optional[PoliteClient] = None,
                 plan: Optional[dict[str, Callable[[], list[Signal]]]] = None) -> tuple[list[Signal], list[dict]]:
    client = client or PoliteClient(min_interval_s=2.0)
    since_dt = _now() - timedelta(days=days)
    ted_log: list = []
    plan = plan if plan is not None else collector_plan(client, since_dt, ted_log)
    found: list[Signal] = []
    logs: list[dict] = []
    for key, fn in plan.items():
        pol = sources.policy(key)
        if not pol.collection_permitted:  # permission gate: never call the collector
            logs.append({"source": key, "result": "skipped", "kind": "permission_not_obtained", "blocker": pol.blocker})
            continue
        try:
            got = fn()
            found.extend(got)
            logs.append({"source": key, "result": "ok", "items": len(got)})
        except FetchBlocked as exc:
            logs.append({"source": key, "result": "failed", "kind": exc.kind, "error": str(exc)[:300]})
    if ted_log:
        logs.append({"source": "ted", "detail": ted_log})
    _write_jsonl(OUT / "discover_log.jsonl", logs)
    _write_jsonl(OUT / "discovered.jsonl", [s.to_dict() for s in found])
    print("discover:", json.dumps([{k: v for k, v in l.items() if k != "detail"} for l in logs]))
    return found, logs


# --------------------------------------------------------------------------- capture (human-assisted)
def cmd_capture(a: argparse.Namespace) -> dict:
    sig = Signal(source=a.source, source_id=a.url, url=a.url, title=a.title, text=make_excerpt(a.excerpt),
                 verification_status="human_verified", posted_at=a.posted_at, collected_at=_now().isoformat(),
                 raw_meta={"kind": "human_capture", "reviewer": a.reviewer})
    path = OUT / "human_captures.jsonl"
    _write_jsonl(path, _read_jsonl(path) + [sig.to_dict()])
    q = qualify(sig, classify(sig))
    print(json.dumps({"intent_tier": q.intent_tier, "queue": q.queue, "reasons": q.reasons, "missing": q.missing_details}, indent=2))
    return q.to_dict()


# --------------------------------------------------------------------------- report
def _cell(v, n: int = 120) -> str:
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v)
    return str(v if v is not None else "").replace("|", "/").replace("\n", " ")[:n]


_ALL_GENUINE: list[dict] = []


def build_report(signals: list[Signal], now: Optional[datetime] = None, max_records: Optional[int] = None,
                 logs: Optional[dict] = None) -> tuple[list[dict], dict, str]:
    now = now or _now()
    kept, dropped = dedupe(signals)
    recs = [qualify(s, classify(s, now=now), now=now).to_dict() for s in kept]
    order = {q: i for i, q in enumerate(QUEUE_ORDER)}
    # Service relevance is screened BEFORE the cap: queue (already relevance-gated), then relevance, then evidence score.
    recs.sort(key=lambda r: (order[r["queue"]], _REL_ORDER.get(r.get("service_relevance", "unknown"), 3), -r["score"],
                             r["published_at"] if r["published_at"] != "unknown" else ""))
    all_genuine = [r for r in recs if r["verification_status"] in ("verified_api", "human_verified")]
    genuine = [r for r in recs if r["verification_status"] in ("verified_api", "human_verified")]
    capped_out = []
    if max_records is not None and len(genuine) > max_records:
        keep_urls = {r["url"] for r in genuine[:max_records]}
        capped_out = [r for r in genuine if r["url"] not in keep_urls]
        recs = [r for r in recs if r["url"] in keep_urls or r["verification_status"] not in ("verified_api", "human_verified")]
        genuine = [r for r in genuine if r["url"] in keep_urls]

    recent_target = [r for r in genuine if r["age_days"] is not None and r["age_days"] <= 30 and r["market"] in ("UK", "UAE", "Europe")]
    funnel = {
        "run_at": now.isoformat(),
        "records_total": len(recs), "duplicates_dropped": len(dropped),
        "genuine_records": len(genuine), "genuine_dropped_by_max_records_cap": len(capped_out),
        "dropped_by_cap_by_relevance": dict(Counter(r.get("service_relevance", "unknown") for r in capped_out)),
        "dropped_by_cap_by_queue": dict(Counter(r["queue"] for r in capped_out)),
        "genuine_by_service_relevance": dict(Counter(r.get("service_relevance", "unknown") for r in all_genuine)),
        "by_verification": dict(Counter(r["verification_status"] for r in recs)),
        "by_queue": {q: sum(1 for r in recs if r["queue"] == q) for q in QUEUE_ORDER},
        "relevant_tenders_needing_process_check": sum(1 for r in genuine if r.get("opportunity_kind") == "tender_bid" and r["queue"] in (PRIORITY_A, PRIORITY_B)),
        "genuine_by_market": dict(Counter(r["market"] for r in genuine)),
        "genuine_by_source": dict(Counter(r["source"] for r in genuine)),
        "verified_in_target_markets_last_30d": len(recent_target),
        "verified_external_provider_demand": sum(1 for r in genuine if r["intent_tier"] in ("A", "B")),
        "verified_with_permitted_contact_route": sum(1 for r in genuine if r["contact_permitted"] and r["queue"] in (PRIORITY_A, PRIORITY_B)),
        "partnership_flagged": sum(1 for r in genuine if r["partnership_opportunity"]),
        "false_positives": "not measurable without human verdicts — review Priority A/B and record verdicts in benchmark/heldout",
    }

    md = ["# Solvant Signal Engine — live lead report", "",
          f"Run: {now.isoformat()}  ·  verified records: **{len(genuine)}**  ·  "
          f"Priority A: **{funnel['by_queue'][PRIORITY_A]}**  ·  B: **{funnel['by_queue'][PRIORITY_B]}**  ·  "
          f"C: **{funnel['by_queue'][PRIORITY_C]}**", "",
          "Budget and delivery complexity are informational only — no prospect is excluded for project size. "
          "Personal contact details are never included; contact through the route the source provides.", "",
          "## Funnel", "", "| Measure | Value |", "|---|---|"]
    for k in ("records_total", "genuine_records", "genuine_dropped_by_max_records_cap", "verified_in_target_markets_last_30d",
              "verified_external_provider_demand", "verified_with_permitted_contact_route", "partnership_flagged"):
        md.append(f"| {k} | {funnel[k]} |")
    md.append(f"| by_queue | {json.dumps(funnel['by_queue'])} |")
    md.append(f"| genuine_by_market | {json.dumps(funnel['genuine_by_market'])} |")
    md.append(f"| genuine_by_source | {json.dumps(funnel['genuine_by_source'])} |")

    for q in QUEUE_ORDER:
        rows = [r for r in recs if r["queue"] == q]
        md += ["", f"## {QUEUE_TITLES[q]} ({len(rows)})", ""]
        if not rows:
            md.append("_None._")
            continue
        if q in (EXCLUDED, UNVERIFIED):
            md += ["| Title | Source | Reason | URL |", "|---|---|---|---|"]
            for r in rows:
                md.append(f"| {_cell(r['title'], 90)} | {r['source']} | {_cell(r['reasons'], 110)} | {r['url']} |")
            continue
        md += ["| Buyer / organisation | Country (evidence) | Business requirement | Published | Evidence URL | Tier | "
               "Service relevance (evidence) | Potential service | Budget (info) | Complexity / flags | Stage / open? | Contact route | Missing |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            req = r["business_requirement"] if not r["business_requirement"].startswith("unknown") else r["title"]
            flags = [r["complexity"]] + r["delivery_flags"] + (["partnership"] if r["partnership_opportunity"] else [])
            md.append(f"| {_cell(r['organisation'], 60)} | {r['country']} ({_cell(r['location_evidence'], 50)}) | "
                      f"{_cell(r['title'], 70)} — {_cell(req, 140)} | {r['published_at'][:10]} | {r['url']} | {r['intent_tier']} | "
                      f"{r['service_relevance']} ({_cell(r['relevance_evidence'], 70)}) | "
                      f"{_cell(r['potential_service'], 70)} | {_cell(r['budget_stated'], 50)} | {_cell(flags, 80)} | "
                      f"{r['procurement_stage']} / {r['availability']} | {_cell(r['contact_route'], 70)} | {_cell(r['missing_details'], 100) or '—'} |")

    md += ["", "## Source permissions", "", permissions_markdown()]
    used = {r["source"] for r in genuine}
    attributions = [sources.policy(k).attribution for k in sorted(used) if sources.policy(k).attribution]
    if attributions:
        md += ["## Attribution", ""] + [f"- {a}" for a in attributions]
    if logs:
        md += ["", "## Fetch logs", "", "```", json.dumps(logs, indent=1, default=str)[:6000], "```"]
    global _ALL_GENUINE
    _ALL_GENUINE = all_genuine
    return recs, funnel, "\n".join(md) + "\n"


def write_csv(path: Path, recs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in recs:
            w.writerow({k: ("; ".join(map(str, r[k])) if isinstance(r.get(k), list) else r.get(k)) for k in CSV_COLUMNS})


def cmd_report(max_records: Optional[int] = None) -> dict:
    signals = [Signal(**d) for d in _read_jsonl(OUT / "verified.jsonl")]
    signals += [Signal(**d) for d in _read_jsonl(OUT / "discovered.jsonl")]
    signals += [Signal(**d) for d in _read_jsonl(OUT / "human_captures.jsonl")]
    seen = {s.url for s in signals}
    signals += [c for c in load_candidates() if c.url not in seen]  # visible, never counted
    logs = {"verify": _read_jsonl(OUT / "verify_log.jsonl"), "discover": _read_jsonl(OUT / "discover_log.jsonl")}
    recs, funnel, md = build_report(signals, max_records=max_records, logs=logs)
    _write_jsonl(OUT / "leads.jsonl", recs)
    _write_jsonl(OUT / "all_records.jsonl", _ALL_GENUINE)  # uncapped audit trail (what the cap dropped is inspectable)
    write_csv(OUT / "lead_report.csv", recs)
    (OUT / "funnel.json").write_text(json.dumps(funnel, indent=2))
    (OUT / "lead_report.md").write_text(md)
    print(json.dumps(funnel, indent=2))
    return funnel


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("probe", "discover", "live", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("--days", type=int, default=30)
        sp.add_argument("--timeout", type=float, default=30, help="per-request timeout in seconds (probe)")
        sp.add_argument("--max-records", type=int, default=100)
    sub.add_parser("verify")
    sub.add_parser("permissions")
    rp = sub.add_parser("report")
    rp.add_argument("--max-records", type=int, default=100)
    cp = sub.add_parser("capture")
    for f in ("url", "title", "excerpt", "posted-at", "reviewer"):
        cp.add_argument(f"--{f}", required=True)
    cp.add_argument("--source", default="human:other")
    a = p.parse_args(argv)
    if a.cmd == "probe":
        cmd_probe(a.days, a.timeout)
    elif a.cmd == "permissions":
        print(permissions_markdown())
    elif a.cmd == "verify":
        cmd_verify()
    elif a.cmd == "discover":
        cmd_discover(a.days)
    elif a.cmd == "report":
        cmd_report(a.max_records)
    elif a.cmd == "capture":
        cmd_capture(a)
    elif a.cmd in ("live", "all"):
        if a.cmd == "all":
            cmd_probe(a.days, a.timeout)
        cmd_discover(a.days)
        cmd_verify()
        cmd_report(a.max_records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
