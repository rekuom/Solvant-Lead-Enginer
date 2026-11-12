#!/usr/bin/env python3
"""Generate supabase/preflight/preflight.sql (read-only) from preflight.template.sql + the objects the migrations create.
`--check` fails if the generated file is stale (PR checks)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "supabase" / "preflight" / "preflight.template.sql"
OUT = ROOT / "supabase" / "preflight" / "preflight.sql"


def build() -> str:
    mig = "".join(p.read_text() for p in sorted((ROOT / "supabase" / "migrations").glob("*.sql")))
    found = {
        "@TABLES@": re.findall(r"create table if not exists solvant\.([a-z_]+)", mig),
        "@FUNCS@": re.findall(r"create or replace function solvant\.([a-z_]+)", mig),
        "@VIEWS@": re.findall(r"create or replace view solvant\.([a-z_]+)", mig),
        "@TYPES@": re.findall(r"create type solvant\.([a-z_]+)", mig),
        "@VERSIONS@": re.findall(r"schema_migrations \(version\) values \('(\d+)'\)", mig),
    }
    sql = TEMPLATE.read_text()
    for k, xs in found.items():
        sql = sql.replace(k, "array[" + ", ".join(f"'{x}'" for x in sorted(set(xs))) + "]")
    return sql


def main() -> int:
    sql = build()
    if "--check" in sys.argv:
        ok = OUT.exists() and OUT.read_text() == sql
        print("preflight in sync" if ok else "preflight STALE: run supabase/scripts/gen_preflight.py")
        return 0 if ok else 1
    OUT.write_text(sql)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
