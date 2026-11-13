#!/usr/bin/env python3
"""Run the read-only Solvant migration preflight against a database and fail on any REJECT.

  python3 supabase/scripts/preflight.py --expect-ref dfnaevcsergsphiiodtm          # DSN from $SUPABASE_DB_URL (CI)
  python3 supabase/scripts/preflight.py --expect-ref dfnaevcsergsphiiodtm --check-uri-only   # validate format, no network
  python3 supabase/scripts/preflight.py "host=/tmp port=55432 user=postgres dbname=postgres"   # local test harness only

Exit codes: 0 = VERDICT OK, 1 = REJECT (target or database checks), 2 = usage / connection string / connection error.

With --expect-ref the connection string MUST be a Supabase Session Pooler URI for that project:
  postgresql://postgres.<ref>:<password>@<region>.pooler.supabase.com:5432/postgres
The connection string and password are never printed. The session is forced read-only
(default_transaction_read_only=on) in addition to BEGIN READ ONLY inside preflight.sql.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

SQL = Path(__file__).resolve().parents[1] / "preflight" / "preflight.sql"
PROJECT_REF = "dfnaevcsergsphiiodtm"
SESSION_POOLER_PORT = 5432
TRANSACTION_POOLER_PORT = 6543


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Read-only Solvant migration preflight")
    ap.add_argument("dsn", nargs="?", default=None, help="connection string (default: $SUPABASE_DB_URL)")
    ap.add_argument("--expect-ref", metavar="PROJECT_REF", default=None,
                    help="require a Session Pooler URI for this Supabase project ref")
    ap.add_argument("--check-uri-only", action="store_true", help="validate the connection string format and exit (no network)")
    return ap.parse_args(argv)


def resolve_dsn(args: argparse.Namespace, env: dict) -> str:
    return (args.dsn or env.get("SUPABASE_DB_URL") or "").strip()


def validate_pooler_uri(dsn: str, ref: str) -> list[str]:
    """Problems with a Supabase Session Pooler URI for `ref`. Messages name fields only — never values of credentials."""
    problems: list[str] = []
    if not dsn:
        return ["connection string is empty (set the SUPABASE_DB_URL secret)"]
    if not (dsn.startswith("postgresql://") or dsn.startswith("postgres://")):
        return ["connection string must be a URI starting with postgresql:// (Supabase → Connect → Session pooler)"]
    try:
        u = urlsplit(dsn)
        port = u.port
    except ValueError:
        return ["connection string is not a valid URI (check for unescaped special characters in the password)"]
    user = unquote(u.username or "")
    expected_user = f"postgres.{ref}"
    if user != expected_user:
        if user == "postgres":
            problems.append(f"username is 'postgres' — the Session Pooler requires '{expected_user}'")
        elif user.startswith("postgres."):
            problems.append("username belongs to a different Supabase project (expected postgres.<this project ref>)")
        else:
            problems.append(f"username must be '{expected_user}'")
    if not u.password:
        problems.append("password is missing from the connection string")
    host = (u.hostname or "").lower()
    if not host.endswith(".pooler.supabase.com"):
        problems.append("host must be the Session Pooler host <region>.pooler.supabase.com (not the direct db.<ref>.supabase.co host)")
    if port == TRANSACTION_POOLER_PORT:
        problems.append("port 6543 is the Transaction pooler; use the Session pooler port 5432")
    elif port not in (None, SESSION_POOLER_PORT):
        problems.append("port must be 5432 (Session pooler)")
    if (u.path or "/postgres").lstrip("/") not in ("postgres", ""):
        problems.append("database name must be 'postgres'")
    return problems


def run(dsn: str) -> list[tuple[str, str, str]]:
    env = {**os.environ, "PGOPTIONS": "-c default_transaction_read_only=on -c client_min_messages=warning"}
    out = subprocess.run(["psql", dsn, "-X", "-q", "-At", "-F", "\x1f", "-v", "ON_ERROR_STOP=1", "-f", str(SQL)],
                         capture_output=True, text=True, env=env, timeout=60)
    if out.returncode != 0:
        msg = out.stderr.replace(dsn, "<connection string>")
        pw = urlsplit(dsn).password if dsn.startswith(("postgresql://", "postgres://")) else None
        if pw:
            msg = msg.replace(pw, "***").replace(unquote(pw), "***")
        sys.stderr.write("preflight could not run: " + msg[-500:] + "\n")
        raise SystemExit(2)
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            rows.append((parts[1], parts[2], parts[3]))
    return rows


def main(argv: Optional[list[str]] = None, env: Optional[dict] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    dsn = resolve_dsn(args, env)
    if args.expect_ref is not None:
        if args.expect_ref != PROJECT_REF:
            print(f"REJECT  target                         --expect-ref must be {PROJECT_REF}; refusing any other project")
            return 1
        problems = validate_pooler_uri(dsn, args.expect_ref)
        if problems:
            for p in problems:
                print(f"REJECT  connection_string              {p}")
            return 2
        print(f"OK      connection_string              Session Pooler URI for project {PROJECT_REF} (credentials not shown)")
    elif not dsn:
        print("REJECT  connection_string              no connection string given (argument or SUPABASE_DB_URL)")
        return 2
    if args.check_uri_only:
        return 0
    rows = run(dsn)
    for status, name, detail in rows:
        print(f"{status:7} {name:30} {detail}")
    verdict = next((s for s, n, _ in rows if n == "VERDICT"), "REJECT")
    return 0 if verdict == "OK" and rows else 1


if __name__ == "__main__":
    sys.exit(main())
