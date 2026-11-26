"""Commercial side of the daily task: proposal drafts and the daily commercial report.

  python -m signal_engine.discovery.platform.commercial drafts out/agent/drafts-YYYYMMDD.json   # save drafts (never sent)
  python -m signal_engine.discovery.platform.commercial report [--limit 8]                     # best live opportunities

Drafts are stored privately in the database (proposals, origin 'claude_draft', status 'draft'); a human reviews, edits and
submits them on the platform. Nothing here contacts anyone. The draft file lives in the git-ignored out/ folder.
Draft file: [{"url": "...", "title": "...", "body": "...", "amount": "1800", "currency": "EUR"}]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from .rest import RestError, rpc

TOKEN = lambda: os.environ.get("SIGNAL_INGEST_TOKEN", "")   # empty -> the proxy-injected header is used
MAX_BODY = 4000


def load_drafts(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    out = []
    for d in (data if isinstance(data, list) else data.get("drafts", []))[:50]:
        if not isinstance(d, dict) or not str(d.get("url", "")).startswith("https://") or not str(d.get("body", "")).strip():
            continue
        out.append({"url": d["url"], "title": str(d.get("title") or "Proposal draft")[:200], "body": str(d["body"]).strip()[:MAX_BODY],
                    "amount": str(d["amount"]) if d.get("amount") not in (None, "") else None,
                    "currency": str(d.get("currency") or "").upper()[:3] or None})
    return out


STATUS = {"confirmed_open": "open (confirmed by board)", "verified_open": "open (confirmed by board)",
          "verified_posted": "posted (availability not stated)", "requirement_stated": "requirement stated in a forum post (open status unconfirmed)",
          "exists": "listing exists (nothing confirmed)"}
CHANGE_SECTIONS = (("new_buyers", "New buyers"), ("updated_leads", "Updated leads"), ("partners", "Agency partnerships"),
                   ("employment", "Employment signals"))


def _budget(r: dict) -> str:
    # the buyer's own amount and currency, verbatim; a conversion or estimate is never shown in its place
    return r.get("budget_text") or "budget not stated"


def format_report(rows: list[dict], funnel: Optional[dict] = None, changes: Optional[dict] = None) -> str:
    L = []
    if funnel:
        L.append("Funnel: " + " → ".join(f"{k.replace('_', ' ')} {funnel.get(k, 0)}" for k in
                 ("open_now", "proposal_possible", "drafts_ready", "proposals_submitted", "replies", "meetings", "won")))
    for i, r in enumerate(rows, 1):
        status = r.get("status_label") or r.get("check_status")
        bits = [_budget(r), f"{r['bids']} offers" if r.get("bids") else "no visible offers" if r.get("status_label") == "requirement_stated" else None,
                f"posted {r['posted']}" if r.get("posted") else None, STATUS.get(status, status),
                "draft ready" if r.get("draft_ready") else None, "SUBMITTED" if r.get("submitted") else None]
        score = f" {r['commercial_score']}" if r.get("commercial_score") is not None else ""
        L.append(f"{i}.{score} [{r.get('priority')}] {r.get('title')}\n   {' · '.join(b for b in bits if b)}")
        if r.get("flags"):
            L.append(f"   Review: {', '.join(r['flags'])}")
        L.append(f"   Next: {r.get('next_step')}\n   {r.get('url')}")
    if not rows:
        L.append("No live opportunities with a concrete next step.")
    if changes:
        for key, label in CHANGE_SECTIONS:
            items = changes.get(key) or []
            L.append(f"{label} ({len(items)})" + ("" if items else ": none"))
            L.extend(f"   - {x.get('title')} · {_budget(x)} · {x.get('url')}" for x in items[:10])
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["drafts"] and len(argv) > 1:
            drafts = load_drafts(argv[1])
            print(json.dumps({"drafts": len(drafts), "database": rpc("save_proposal_drafts", {"p_token": TOKEN(), "p_drafts": drafts})}))
            return 0
        if argv[:1] == ["report"]:
            limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 8
            rows = rpc("commercial_shortlist", {"p_token": TOKEN(), "p_limit": limit}) or []
            try:
                changes = rpc("daily_changes", {"p_token": TOKEN(), "p_hours": 24}) or {}
            except RestError:
                changes = None      # older database without daily_changes: report without the change sections
            print(format_report(rows, rpc("funnel_for_report", {"p_token": TOKEN()}) or {}, changes))
            return 0
    except RestError as exc:
        print(f"commercial: database call failed (HTTP {exc.status})")
        return 3
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
