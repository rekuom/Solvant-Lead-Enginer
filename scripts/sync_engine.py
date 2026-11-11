#!/usr/bin/env python3
"""Copy the Python engine (poc/signal_engine) into web/api/_engine so the Vercel Python function deploys the SAME,
tested code. `--check` fails if the copy is stale (run in PR checks). Stdlib only; tests and caches are not copied."""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "poc" / "signal_engine"
DST = ROOT / "web" / "api" / "_engine" / "signal_engine"
SKIP = {"__pycache__"}


def files(base: Path) -> set[Path]:
    return {p.relative_to(base) for p in base.rglob("*") if p.is_file() and not (set(p.parts) & SKIP) and p.suffix in (".py", ".json")}


def main() -> int:
    src, dst = files(SRC), files(DST) if DST.exists() else set()
    stale = sorted(str(p) for p in src ^ dst) + sorted(str(p) for p in src & dst if not filecmp.cmp(SRC / p, DST / p, shallow=False))
    if "--check" in sys.argv:
        print("engine copy in sync" if not stale else f"engine copy STALE ({len(stale)} files): run python3 scripts/sync_engine.py")
        return 1 if stale else 0
    if DST.exists():
        shutil.rmtree(DST)
    for p in sorted(src):
        (DST / p).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / p, DST / p)
    print(f"copied {len(src)} files to {DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
