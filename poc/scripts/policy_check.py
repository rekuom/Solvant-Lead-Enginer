#!/usr/bin/env python3
"""Offline policy checks (no network, no secrets). Run from poc/.

  python scripts/policy_check.py                    # workflows + source registry + Brave policy constants
  python scripts/policy_check.py --artifacts DIR    # scan PUBLIC artifacts in DIR before upload

Exit code 1 on any violation. Text-based workflow checks keep this stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
ROOT = POC.parent
sys.path.insert(0, str(POC))

WF = ROOT / ".github" / "workflows"
PR_CHECK = "pr-checks.yml"
# secret name -> workflows allowed to reference it (and only inside the named step)
ALLOWED_SECRETS = {"BRAVE_SEARCH_API_KEY": {"multi-source-discovery.yml"}}
ALLOWED_VARS = {"BRAVE_STORAGE_RIGHTS_ATTESTATION": {"multi-source-discovery.yml"}}
PUBLIC_FILES = ("report_public.md", "report_public.csv", "report_public.jsonl", "stage_audit.json", "run_log.json")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w.])\+\d[\d ()-]{8,}\d")
PRIVATE_NAMES = ("raw_discovered", "opportunities_private", "private_brave", "intake.jsonl", "review_packet", "query_log")


def _on_block(text: str) -> str:
    m = re.search(r"^on:\s*\n((?:[ \t]+.*\n|\s*\n)+)", text, re.M)
    return m.group(1) if m else ""


def check_workflows() -> list[str]:
    errs: list[str] = []
    files = sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml"))
    if not any(f.name == PR_CHECK for f in files):
        errs.append(f"{PR_CHECK} missing")
    for f in files:
        t = f.read_text()
        n = f.name
        triggers = set(re.findall(r"^  ([a-z_]+):", _on_block(t), re.M))
        if re.search(r"^\s+schedule:", t, re.M) or "cron:" in t:
            errs.append(f"{n}: scheduled trigger not allowed (manual collection only)")
        if "pull_request_target" in t:
            errs.append(f"{n}: pull_request_target not allowed")
        if not re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", t, re.M):
            errs.append(f"{n}: top-level 'permissions: contents: read' required")
        if re.search(r":\s*write\b", t):
            errs.append(f"{n}: write permission found")
        if n == PR_CHECK:
            if triggers - {"pull_request", "workflow_dispatch"}:
                errs.append(f"{n}: unexpected triggers {sorted(triggers)}")
            if re.search(r"\$\{\{\s*(secrets|vars)\.", t):
                errs.append(f"{n}: PR checks must not reference secrets or variables")
            live = [l for l in t.splitlines() if "--enable-brave" in l or "validate live" in l
                    or ("discovery.run discover" in l and "--dry-run" not in l)]
            if live:
                errs.append(f"{n}: PR checks must not run live collection: {live}")
        else:
            if triggers != {"workflow_dispatch"}:
                errs.append(f"{n}: live workflows must be workflow_dispatch only (found {sorted(triggers)})")
        for kind, allowed in (("secrets", ALLOWED_SECRETS), ("vars", ALLOWED_VARS)):
            for name in re.findall(rf"\$\{{\{{\s*{kind}\.([A-Z0-9_]+)", t):
                if n not in allowed.get(name, set()):
                    errs.append(f"{n}: {kind}.{name} not allowed here")
        if "BRAVE_SEARCH_API_KEY" in t:
            # the key may appear only in the Discover step's env
            steps = re.split(r"\n      - ", t)
            holders = [s.splitlines()[0] for s in steps if "secrets.BRAVE_SEARCH_API_KEY" in s]
            if any("Discover" not in h for h in holders):
                errs.append(f"{n}: BRAVE_SEARCH_API_KEY referenced outside the Discover step: {holders}")
        if "upload-artifact" in t:
            for seg in t.split("upload-artifact")[1:]:
                block = seg.split("\n      - ")[0]
                for p in PRIVATE_NAMES:
                    if p in block:
                        errs.append(f"{n}: private file '{p}' in an artifact upload")
    return errs


def check_registry() -> list[str]:
    from signal_engine.discovery import registry
    from signal_engine.discovery import run as runmod
    from signal_engine.discovery.connectors import search
    errs: list[str] = []
    try:
        srcs = registry.load()
    except registry.PolicyError as exc:
        return [f"registry: {exc}"]
    for key, s in srcs.items():
        allowed, _ = registry.may_collect(key)
        if s["status"] != "permitted" and allowed:
            errs.append(f"registry: {key} ({s['status']}) collectable without explicit opt-in")
        if s["status"] in ("unknown", "prohibited") and registry.may_collect(key, [key])[0]:
            errs.append(f"registry: {key} ({s['status']}) collectable even with opt-in")
    b = srcs.get("web_search_brave")
    if not b or "storage" not in b["notes"].lower():
        errs.append("registry: web_search_brave must document the storage-rights restriction")
    if runmod.BRAVE_HARD_CAP > 100:
        errs.append("Brave hard cap above 100")
    if search.brave_storage_rights_attested(True, {})[0]:
        errs.append("Brave retention possible without operator attestation")
    return errs


def check_artifacts(d: Path) -> list[str]:
    errs: list[str] = []
    for name in PUBLIC_FILES:
        f = d / name
        if not f.exists():
            continue
        t = f.read_text()
        for m in EMAIL.findall(t):
            errs.append(f"{name}: e-mail address in public artifact ({m.split('@')[0][:2]}…@…)")
        if PHONE.search(t):
            errs.append(f"{name}: phone-number-like string in public artifact")
        if name.startswith("report_public") and ("\"web_search_brave\"" in t or "search_snippet_only" in t):
            errs.append(f"{name}: Brave search output in public report")
        if name == "report_public.jsonl":
            for line in t.splitlines():
                if line.strip() and json.loads(line)["record"]["source_key"] == "web_search_brave":
                    errs.append(f"{name}: Brave record in public report")
        if name == "stage_audit.json" and '"duplicates":' in t:
            errs.append(f"{name}: per-record duplicate log present (counts only allowed)")
        if name == "run_log.json":
            agg = json.loads(t).get("brave_aggregate") or {}
            if re.search(r"https?://", json.dumps(agg)):
                errs.append(f"{name}: URL inside Brave aggregate")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", type=Path)
    a = ap.parse_args()
    errs = check_artifacts(a.artifacts) if a.artifacts else check_workflows() + check_registry()
    for e in errs:
        print(f"::error::{e}")
    print(f"policy_check: {'FAILED' if errs else 'OK'} ({len(errs)} violation(s))")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
