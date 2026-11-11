"""Phase 4 discovery CLI (run from poc/).

  python3 -m signal_engine.discovery.run sources                          # registry table
  python3 -m signal_engine.discovery.run plan --provider github --max-queries 15
  python3 -m signal_engine.discovery.run discover --sources github_issues --since-days 45 --max-requests 15 [--dry-run]
       [--allow-restricted hn_algolia] [--include-discussions]
  python3 -m signal_engine.discovery.run intake add --source-key linkedin --url ... --post-date ... --text ... [--organisation ...]
  python3 -m signal_engine.discovery.run intake csv FILE | json FILE | email FILE.eml
  python3 -m signal_engine.discovery.run report [--shortlist 20]
  python3 -m signal_engine.discovery.run review-packet --pipeline A_DIRECT_SME --top 20
  python3 -m signal_engine.discovery.run score-review LABELS.csv

Outputs (poc/out/discovery/, git-ignored):
  raw_discovered.jsonl      raw records (author handles hashed)
  opportunities_private.jsonl  every assessed record (private: stays on the runner / local disk)
  report_public.md / .csv   REDACTED report (safe for Actions artifacts of a public repository)
  stage_audit.json          counts at every stage + omitted-record reasons (nothing silently dropped)
  run_log.json              per-connector request log (failures are never hidden) + Brave counts (no URLs)
  Brave search output is never written here unless storage rights are attested (then: private_brave_review_attested.jsonl,
  never uploaded or reported).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..textutil import canonical_url, fingerprint
from . import intake, querylib, registry
from .assess import assess
from .connectors import github as gh
from .connectors import hn
from .connectors.search import (BraveProvider, ProviderDisabled, apply_brave_policy, brave_storage_rights_attested, run_feeds,
                                run_search, verify_landing)
from .models import PIPELINES, RawRecord
from .privacy import clean_text, public_view
from .router import build, mark_spam_campaigns

OUT = Path("out/discovery")
PUBLIC_PIPELINES = {"A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER", "E_PROCUREMENT", "G_LICENSED_LEADS", "GLOBAL_REVIEW"}
DIRECT_ORDER = ["A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER", "D_OPERATIONAL_PAIN", "E_PROCUREMENT",
                "F_RECRUITMENT_SIGNAL", "G_LICENSED_LEADS", "GLOBAL_REVIEW", "H_RESEARCH_UNVERIFIED", "EXCLUDED"]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _read_raw(path: Path) -> list[RawRecord]:
    return [RawRecord(**json.loads(l)) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


# ----------------------------------------------------------------------------- discover
BRAVE_HARD_CAP = 100   # first-test ceiling; never exceeded regardless of input


def discover(sources: list[str], since_days: int, max_requests: int, dry_run: bool, allow_restricted: list[str],
             include_discussions: bool = False, max_queries: int = 20, enable_brave: bool = False,
             brave_max_requests: int = 100, brave_freshness: str = "pm", brave_retention_permitted: bool = False) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).date().isoformat()
    qlog = querylib.QueryLog(OUT / "query_log.json")
    records: list[RawRecord] = []
    logs = []
    brave_aggregate: Optional[dict] = None
    import time
    for src in sources:
        t0, n_logs = time.monotonic(), len(logs)
        if src == "github_issues":
            qs = querylib.plan("github", since, max_queries=max_queries)
            got, log = gh.search_issues(qs, max_requests=max_requests, querylog=qlog, dry_run=dry_run)
            records += got
            logs.append(log.to_dict())
            if include_discussions:
                import os
                got, log = gh.search_discussions(qs, os.environ.get("GITHUB_TOKEN"), max_requests=min(5, max_requests), dry_run=dry_run)
                records += got
                logs.append(log.to_dict())
        elif src == "hn_algolia":
            if dry_run:
                got, log = [], hn.RunLog("hn_algolia")
                log.skipped, _ = 1, log.event(kind="dry_run", detail="seeking-freelancer thread not fetched")
            else:
                got, log = hn.seeking_freelancer(allow_restricted=allow_restricted)
            qs = querylib.plan("hn", since, max_queries=max_queries)
            ts = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())
            got2, log2 = hn.search(qs, allow_restricted=allow_restricted, since_ts=ts, max_requests=max_requests, dry_run=dry_run)
            records += got + got2
            logs += [log.to_dict(), log2.to_dict()]
        elif src in ("procurement", "contracts_finder", "find_a_tender", "ted"):
            from .connectors import procurement
            keys = procurement.KEYS if src == "procurement" else (src,)
            got, plogs = procurement.collect(keys, since_days=since_days, max_pages=min(5, max(1, max_requests // 4)), dry_run=dry_run)
            records += got
            logs += [l.to_dict() for l in plogs]
        elif src == "feeds":
            got, log = run_feeds()
            records += got
            logs.append(log.to_dict())
        elif src == "search:brave":
            cap = max(0, min(BRAVE_HARD_CAP, brave_max_requests))
            qs = querylib.plan_web("brave", max_requests=cap)
            plan_cost = round(sum(q.est_cost_usd for q in qs), 3)
            if dry_run or not enable_brave:
                logs.append({"source": "search:brave", "status": "skipped", "requests": 0, "planned_requests": len(qs),
                             "est_cost_usd_if_run": plan_cost, "detail": "dry-run: Brave not explicitly enabled" if not enable_brave else "dry-run",
                             "plan_by_category": dict(Counter(q.category for q in qs)), "plan_by_market": dict(Counter(q.market for q in qs))})
                continue
            try:
                prov = BraveProvider(freshness=brave_freshness)
            except ProviderDisabled as exc:
                logs.append({"source": "search:brave", "status": "skipped", "requests": 0, "planned_requests": len(qs), "detail": str(exc)})
                continue
            got, log = run_search(prov, qs, max_requests=cap)
            log.event(kind="authorisation", detail="licensed provider: operator enabled with a configured key")
            import os
            # Brave output is processed IN MEMORY only. Permitted original-source APIs re-fetch what they can; the
            # rest is reduced to non-identifying counts. Nothing from Brave is written to disk unless storage rights are attested.
            got, vlog = verify_landing(got, token=os.environ.get("GITHUB_TOKEN"), max_requests=20, allow_restricted=allow_restricted)
            attested, why = brave_storage_rights_attested(brave_retention_permitted)
            kept, brave_aggregate = apply_brave_policy(got, attested)
            del got
            brave_aggregate["retention_decision"] = why
            records += [r for r in kept if r.source_key != "web_search_brave"]          # original-source data only
            snippets = [r for r in kept if r.source_key == "web_search_brave"]
            if snippets:   # only reachable with attested storage rights; private file, never uploaded or reported
                _write_jsonl(OUT / "private_brave_review_attested.jsonl", [r.to_dict() for r in snippets])
            logs += [log.to_dict(), vlog.to_dict()]
        else:
            logs.append({"source": src, "status": "unknown_source", "requests": 0})
        for l in logs[n_logs:]:
            l.setdefault("duration_s", 0)
            l["duration_s"] = round(time.monotonic() - t0, 1) if l["duration_s"] == 0 else l["duration_s"]
    qlog.save()
    prev = _read_raw(OUT / "raw_discovered.jsonl")
    merged = {r.url: r for r in prev if r.source_key != "web_search_brave"}
    for r in records:
        if r.source_key == "web_search_brave":   # defence in depth: Brave output never enters the raw store
            continue
        merged[r.url] = r
    _write_jsonl(OUT / "raw_discovered.jsonl", [r.to_dict() for r in merged.values()])
    run = {"run_at": datetime.now(timezone.utc).isoformat(), "dry_run": dry_run, "since": since, "sources": sources,
           "allow_restricted": allow_restricted, "logs": logs, "new_records": len(records), "total_raw": len(merged)}
    if brave_aggregate is not None:
        run["brave_aggregate"] = brave_aggregate     # counts only: no URL, title, snippet or domain list
    (OUT / "run_log.json").write_text(json.dumps(run, indent=1, default=str))
    return run


# ----------------------------------------------------------------------------- report
def build_opportunities(raw: list[RawRecord], now: Optional[datetime] = None) -> tuple[list, dict]:
    now = now or datetime.now(timezone.utc)
    audit: dict = {"stage_1_raw": len(raw), "by_source_raw": dict(Counter(r.source_key for r in raw))}
    # dedupe before ranking: canonical URL, then content fingerprint
    # Duplicates are reported as COUNTS only (by reason and source family): URLs of duplicates are never written anywhere.
    seen_u, seen_f, uniq = {}, {}, []
    dup_reason, dup_source = Counter(), Counter()
    for r in raw:
        cu, fp = canonical_url(r.url), fingerprint(r.title + " " + r.body)
        reason = "same_url" if cu in seen_u else "same_content" if (fp in seen_f and len(r.body) > 40) else None
        if reason:
            dup_reason[reason] += 1
            dup_source[r.source_key] += 1
            continue
        seen_u[cu], seen_f[fp] = r.url, r.url
        uniq.append(r)
    audit["stage_2_after_dedupe"] = len(uniq)
    audit["duplicates_removed"] = sum(dup_reason.values())
    audit["duplicates_by_reason"] = dict(dup_reason)
    audit["duplicates_by_source"] = dict(dup_source)
    spam = mark_spam_campaigns(uniq)
    opps = []
    for r in uniq:
        a = assess(r, now=now)
        if r.source_id in spam:
            a.noise_flags = sorted(set(a.noise_flags) | {"spam_campaign"})
        opps.append(build(r, a))
    audit["stage_3_verified_content"] = sum(1 for o in opps if o.record.verification in ("api_verified", "reviewer_verified"))
    audit["stage_3_user_supplied"] = sum(1 for o in opps if o.record.verification in ("user_submitted", "licensed_import"))
    audit["stage_3_snippet_only"] = sum(1 for o in opps if o.record.verification == "search_snippet_only")
    audit["stage_4_technical_relevance"] = dict(Counter(o.assessment.technical_relevance.value for o in opps))
    audit["stage_5_buying_intent"] = dict(Counter(o.assessment.buying_intent.value for o in opps))
    audit["stage_6_pipelines"] = {p: sum(1 for o in opps if o.pipeline == p) for p in DIRECT_ORDER}
    audit["noise_flags"] = dict(Counter(f for o in opps for f in o.assessment.noise_flags))
    audit["exclusion_reasons"] = dict(Counter(o.pipeline_reason for o in opps if o.pipeline == "EXCLUDED"))
    return opps, audit


GENUINE_INTENTS = {"explicit_hire_request", "quote_request", "recommendation_request", "partner_search", "paid_bounty"}


def source_metrics(opps: list, logs: list[dict]) -> dict:
    """Per-source metrics for the first operational validation. False positives need human review: never estimated here."""
    out: dict[str, dict] = {}
    for o in opps:
        src = o.record.source_key + (f"[via {o.record.meta.get('discovered_via')}]" if o.record.meta.get("discovered_via") else "")
        m = out.setdefault(src, {"records_found": 0, "records_verified": 0, "genuine_implementation_requests": 0, "direct_sme": 0,
                                 "freelance_projects": 0, "agency_partnerships": 0, "permitted_contact_routes": 0,
                                 "by_query_category": Counter(), "false_positives": "requires human review (blind packet)"})
        a = o.assessment
        m["records_found"] += 1
        m["records_verified"] += o.record.verification in ("api_verified", "reviewer_verified")
        verified_buyer = o.pipeline in ("A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER")
        m["genuine_implementation_requests"] += verified_buyer and a.buying_intent.value in GENUINE_INTENTS and a.technical_relevance.value == "relevant"
        m["direct_sme"] += o.pipeline == "A_DIRECT_SME"
        m["freelance_projects"] += o.pipeline == "B_FREELANCE_PROJECT"
        m["agency_partnerships"] += o.pipeline == "C_AGENCY_PARTNER"
        m["permitted_contact_routes"] += verified_buyer and a.contact_permission.value in ("reply_in_thread_invited", "in_platform_only", "per_platform_rules")
        m["by_query_category"][o.record.meta.get("query_category") or "n/a"] += 1
    for l in logs:
        k = l["source"]
        m = out.setdefault(k, {"records_found": 0})
        m.update({"requests": l.get("requests", 0), "failed_requests": l.get("failed", 0), "status": l.get("status"),
                  "est_cost_usd": l.get("est_cost_usd", 0), "runtime_s": l.get("duration_s", 0)})
    for m in out.values():
        if isinstance(m.get("by_query_category"), Counter):
            m["by_query_category"] = dict(m["by_query_category"])
    return out


def report(shortlist: int = 20) -> dict:
    # Brave snippets are never reported record-by-record, whatever the plan: public outputs carry only original-source
    # records (independently verified) and Brave counts from run_log["brave_aggregate"].
    raw = [r for r in _read_raw(OUT / "raw_discovered.jsonl") + intake.load_store() if r.source_key != "web_search_brave"]
    opps, audit = build_opportunities(raw)
    run_log = json.loads((OUT / "run_log.json").read_text()) if (OUT / "run_log.json").exists() else {"logs": []}
    audit["source_metrics"] = source_metrics(opps, run_log.get("logs", []))
    audit["brave_record_level_output"] = ("never published: Brave results appear only as non-identifying counts; "
                                          "records shown were re-fetched from the original source's permitted API")
    if run_log.get("brave_aggregate"):
        audit["brave_aggregate"] = run_log["brave_aggregate"]
    order = {p: i for i, p in enumerate(DIRECT_ORDER)}
    opps.sort(key=lambda o: (order[o.pipeline], -o.rank_score))
    # shortlist per pipeline; everything else is retained (private) and counted with a reason
    shown, omitted = [], Counter()
    per = Counter()
    for o in opps:
        if o.pipeline == "EXCLUDED":
            continue
        if per[o.pipeline] < shortlist:
            shown.append(o)
            per[o.pipeline] += 1
        else:
            omitted[o.pipeline] += 1
    audit["stage_7_shortlisted"] = dict(per)
    audit["omitted_beyond_shortlist_retained_privately"] = dict(omitted)
    _write_jsonl(OUT / "opportunities_private.jsonl", [o.to_dict() for o in opps])   # runner-local; deleted when the job ends
    # PUBLIC repository: only actionable pipelines are listed record-by-record in public outputs;
    # research / excluded records appear as counts only (their detail stays in the private file).
    shown = [o for o in shown if o.pipeline in PUBLIC_PIPELINES and o.record.verification != "fixture"]
    pub = [public_view(o.to_dict()) for o in shown]
    _write_jsonl(OUT / "report_public.jsonl", pub)
    with (OUT / "report_public.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pipeline", "rank", "title", "url", "source", "created_at", "state", "verification", "technical_relevance",
                    "buying_intent", "engagement_type", "business_type", "decision_maker_access", "freshness", "contact_permission",
                    "location", "budget", "noise_flags", "suggested_service", "missing_facts", "next_action", "pipeline_reason"])
        for o in shown:
            a = o.assessment
            w.writerow([o.pipeline, o.rank_score, clean_text(o.record.title, limit=140), o.record.url, o.record.source_key, o.record.created_at,
                        o.record.state, o.record.verification, a.technical_relevance.value, a.buying_intent.value, a.engagement_type.value,
                        a.business_type.value, a.decision_maker_access.value, a.freshness.value, a.contact_permission.value,
                        a.location.value, "; ".join(a.commercial_potential.evidence), "; ".join(a.noise_flags), a.suggested_service,
                        "; ".join(a.missing_facts), o.next_action, o.pipeline_reason])
    (OUT / "stage_audit.json").write_text(json.dumps(audit, indent=1, default=str))
    (OUT / "report_public.md").write_text(_markdown(shown, audit))
    return audit


def _markdown(shown: list, audit: dict) -> str:
    L = ["# Discovery report (redacted)", "", f"Generated {datetime.now(timezone.utc).isoformat()}. Author handles are hashed and omitted; "
         "excerpts are PII-redacted. No record here has been contacted.", "", "## Stage audit", "", "```json",
         json.dumps(audit, indent=1, default=str), "```"]
    L += ["", "## Per-source results", "", "| Source | Status | Requests | Failed | Found | Verified | Genuine requests | Direct SME | Freelance | Agency | Contact route | Est. cost $ | Runtime s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, m in audit.get("source_metrics", {}).items():
        L.append(f"| {k} | {m.get('status', '—')} | {m.get('requests', '—')} | {m.get('failed_requests', '—')} | {m.get('records_found', 0)} | "
                 f"{m.get('records_verified', '—')} | {m.get('genuine_implementation_requests', '—')} | {m.get('direct_sme', '—')} | "
                 f"{m.get('freelance_projects', '—')} | {m.get('agency_partnerships', '—')} | {m.get('permitted_contact_routes', '—')} | "
                 f"{m.get('est_cost_usd', 0)} | {m.get('runtime_s', '—')} |")
    L += ["", "False positives are not estimated automatically: they require the blind human review packet.",
          f"Brave record-level output: {audit.get('brave_record_level_output')}"]
    for p in DIRECT_ORDER[:-1]:
        rows = [o for o in shown if o.pipeline == p]
        L += ["", f"## {p} — {PIPELINES[p]} ({len(rows)})", ""]
        if p not in PUBLIC_PIPELINES:
            L.append(f"_Counts only in public output ({audit['stage_6_pipelines'].get(p, 0)} records); details are kept privately on the runner._")
            continue
        if not rows:
            L.append("_None._")
            continue
        L += ["| Rank | Title | Source | Created | Intent | Relevance | Engagement | Business | Contact | Why | URL |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for o in rows:
            a = o.assessment
            L.append(f"| {o.rank_score} | {clean_text(o.record.title, limit=80).replace('|', '/')} | {o.record.source_key} | {(o.record.created_at or '')[:10]} | "
                     f"{a.buying_intent.value} | {a.technical_relevance.value} | {a.engagement_type.value} | {a.business_type.value} | "
                     f"{a.contact_permission.value} | {o.pipeline_reason[:70].replace('|', '/')} | {o.record.url} |")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- blind review
def review_packet(pipeline: str, top: int) -> Path:
    """Blind packet: source evidence only — NO model judgement — for an independent human reviewer."""
    rows = [json.loads(l) for l in (OUT / "opportunities_private.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["pipeline"] == pipeline]
    rows.sort(key=lambda r: -r["rank_score"])
    path = OUT / f"review_packet_{pipeline}.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "url", "source", "created_at", "title", "excerpt",
                    "LABEL_genuine_commercial_opportunity(y/n)", "LABEL_service_relevant(y/n)", "LABEL_explicit_buying_intent(y/n)",
                    "LABEL_business_type(sme/larger/agency/enterprise/public/individual/unknown)",
                    "LABEL_engagement(agency_consultancy/freelance/employment/partnership/procurement/unknown)",
                    "LABEL_contact_route_ok(y/n)", "LABEL_notes"])
        for i, r in enumerate(rows[:top], 1):
            rec = r["record"]
            w.writerow([i, rec["url"], rec["source_key"], rec["created_at"], rec["title"], rec["body"][:600], "", "", "", "", "", "", ""])
    (OUT / f"review_key_{pipeline}.json").write_text(json.dumps(
        [{"item": i, "url": r["record"]["url"], "pipeline": r["pipeline"], "assessment": r["assessment"]} for i, r in enumerate(rows[:top], 1)],
        default=str))
    return path


def score_review(labels_csv: Path, pipeline: str) -> dict:
    labels = intake.read_csv(labels_csv)
    key = {k["item"]: k for k in json.loads((OUT / f"review_key_{pipeline}.json").read_text())}
    yes = lambda v: str(v).strip().lower() in ("y", "yes", "1", "true")
    rows = [l for l in labels if str(l.get("LABEL_genuine_commercial_opportunity(y/n)", "")).strip()]
    n = len(rows)
    def p_at(k):
        sub = rows[:k]
        return sum(yes(r["LABEL_genuine_commercial_opportunity(y/n)"]) for r in sub), len(sub)
    def agree(label_col, dim, mapping=lambda x: x):
        pairs = [(mapping(r[label_col]), key[int(r["item"])]["assessment"][dim]["value"]) for r in rows if r.get(label_col)]
        return sum(1 for h, m in pairs if h and h in m), len(pairs)
    res = {"pipeline": pipeline, "reviewed": n, "precision_at_10": p_at(10), "precision_at_20": p_at(20),
           "service_relevance_precision": (sum(yes(r["LABEL_service_relevant(y/n)"]) for r in rows), n),
           "buying_intent_precision": (sum(yes(r["LABEL_explicit_buying_intent(y/n)"]) for r in rows), n),
           "business_type_agreement": agree("LABEL_business_type(sme/larger/agency/enterprise/public/individual/unknown)", "business_type"),
           "engagement_agreement": agree("LABEL_engagement(agency_consultancy/freelance/employment/partnership/procurement/unknown)", "engagement_type"),
           "contact_route_ok": (sum(yes(r["LABEL_contact_route_ok(y/n)"]) for r in rows), n),
           "gate_note": "90% gate requires >= 20 reviewed items; " + ("enough items" if n >= 20 else f"only {n} reviewed — gate cannot be assessed")}
    (OUT / f"review_scores_{pipeline}.json").write_text(json.dumps(res, indent=1))
    return res


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources")
    pl = sub.add_parser("plan"); pl.add_argument("--provider", default="github"); pl.add_argument("--max-queries", type=int, default=15)
    pl.add_argument("--since-days", type=int, default=45)
    d = sub.add_parser("discover")
    d.add_argument("--sources", default="github_issues"); d.add_argument("--since-days", type=int, default=45)
    d.add_argument("--max-requests", type=int, default=15); d.add_argument("--max-queries", type=int, default=20)
    d.add_argument("--dry-run", action="store_true"); d.add_argument("--allow-restricted", default="")
    d.add_argument("--include-discussions", action="store_true")
    d.add_argument("--enable-brave", action="store_true", help="explicitly allow live Brave requests (needs BRAVE_SEARCH_API_KEY)")
    d.add_argument("--brave-max-requests", type=int, default=100)
    d.add_argument("--brave-freshness", default="pm", choices=["pd", "pw", "pm", "py"])
    d.add_argument("--brave-retention-permitted", action="store_true",
                   help="request retention; ALSO needs the BRAVE_STORAGE_RIGHTS_ATTESTATION variable. Even then snippets stay private")
    it = sub.add_parser("intake"); isub = it.add_subparsers(dest="how", required=True)
    ia = isub.add_parser("add")
    for f in intake.FIELDS:
        ia.add_argument(f"--{f.replace('_', '-')}", required=f in ("source_key", "url"))
    ia.add_argument("--verified-by", help="reviewer label: you opened the ORIGINAL URL and copied the text from it")
    for how in ("csv", "json", "email"):
        x = isub.add_parser(how); x.add_argument("file"); x.add_argument("--source-key")
        x.add_argument("--fixture", action="store_true", help="synthetic test data: stored as 'fixture', never a lead")
    r = sub.add_parser("report"); r.add_argument("--shortlist", type=int, default=20)
    rp = sub.add_parser("review-packet"); rp.add_argument("--pipeline", default="A_DIRECT_SME"); rp.add_argument("--top", type=int, default=20)
    sr = sub.add_parser("score-review"); sr.add_argument("labels"); sr.add_argument("--pipeline", default="A_DIRECT_SME")
    a = p.parse_args(argv)
    if a.cmd == "sources":
        print(registry.table_markdown())
    elif a.cmd == "plan":
        since = (datetime.now(timezone.utc) - timedelta(days=a.since_days)).date().isoformat()
        qs = querylib.plan(a.provider, since, max_queries=a.max_queries)
        for q in qs:
            print(f"{q.query_id:28} {q.lang} conf={q.translation_confidence:6} est=${q.est_cost_usd:.3f} | {q.query}")
        print(f"{len(qs)} queries; estimated cost ${sum(q.est_cost_usd for q in qs):.3f}")
    elif a.cmd == "discover":
        run = discover([s.strip() for s in a.sources.split(",") if s.strip()], a.since_days, a.max_requests, a.dry_run,
                       [s.strip() for s in a.allow_restricted.split(",") if s.strip()], a.include_discussions, a.max_queries,
                       a.enable_brave, a.brave_max_requests, a.brave_freshness, a.brave_retention_permitted)
        print(json.dumps({k: v for k, v in run.items() if k != "logs"}, indent=1))
        for l in run["logs"]:
            print(f"  {l['source']}: {l['status']} requests={l.get('requests')} records={l.get('records')}")
        failed = [l for l in run["logs"] if l["status"] in ("failed", "partial")]
        return 2 if failed else 0
    elif a.cmd == "intake":
        if a.how == "add":
            rows = [{f: getattr(a, f) for f in intake.FIELDS}]
        elif a.how == "csv":
            rows = intake.read_csv(Path(a.file))
        elif a.how == "json":
            rows = intake.read_json(Path(a.file))
        else:
            rows = intake.read_email(Path(a.file), a.source_key)
        if a.how != "add" and getattr(a, "source_key", None):
            for r in rows:
                r.setdefault("source_key", a.source_key)
        print(json.dumps(intake.add(rows, a.how, fixture=getattr(a, "fixture", False), verified_by=getattr(a, "verified_by", None)), indent=1))
    elif a.cmd == "report":
        print(json.dumps(report(a.shortlist), indent=1, default=str))
    elif a.cmd == "review-packet":
        print(review_packet(a.pipeline, a.top))
    elif a.cmd == "score-review":
        print(json.dumps(score_review(Path(a.labels), a.pipeline), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
