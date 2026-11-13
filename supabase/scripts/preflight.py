#!/usr/bin/env python3
"""Run the read-only preflight against a database and fail on any REJECT.

  python3 supabase/scripts/preflight.py "$DATABASE_URL" [--expect-ref dfnaevcsergsphiiodtm]

The connection string is read from the argument or SUPABASE_DB_URL and is never printed. The session is forced read-only
(default_transaction_read_only=on) in addition to the BEGIN READ ONLY inside preflight.sql.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SQL = Path(__file__).resolve().parents[1] / "preflight" / "preflight.sql"
PROJECT_REF = "dfnaevcsergsphiiodtm"


def run(dsn: str) -> list[tuple[str, str, str]]:
    env = {**os.environ, "PGOPTIONS": "-c default_transaction_read_only=on -c client_min_messages=warning"}
    out = subprocess.run(["psql", dsn, "-X", "-q", "-At", "-F", "\x1f", "-v", "ON_ERROR_STOP=1", "-f", str(SQL)],
                         capture_output=True, text=True, env=env, timeout=60)
    if out.returncode != 0:
        sys.stderr.write("preflight could not run: " + out.stderr.replace(dsn, "<dsn>")[-500:] + "\n")
        raise SystemExit(2)
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            rows.append((parts[1], parts[2], parts[3]))
    return rows


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dsn = args[0] if args else os.environ.get("SUPABASE_DB_URL", "")
    if not dsn:
        print("usage: preflight.py <connection string> (or set SUPABASE_DB_URL)")
        return 2
    if "--expect-ref" in sys.argv:
        ref = sys.argv[sys.argv.index("--expect-ref") + 1]
        if ref != PROJECT_REF or ref not in dsn:
            print(f"REJECT  target  connection string is not for project {PROJECT_REF}")
            return 1
    rows = run(dsn)
    for status, name, detail in rows:
        print(f"{status:7} {name:30} {detail}")
    verdict = next((s for s, n, _ in rows if n == "VERDICT"), "REJECT")
    return 0 if verdict == "OK" and rows else 1


if __name__ == "__main__":
    sys.exit(main())
