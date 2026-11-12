#!/usr/bin/env bash
# Spin up a throwaway local Postgres, apply the migrations on top of a Supabase stub, run the security tests.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
BIN="${PG_BIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | tail -1)}"
WORK="$(mktemp -d)"; PORT="${PG_PORT:-55432}"
trap '"$BIN/pg_ctl" -D "$WORK/data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
if [ "$(id -u)" = "0" ]; then RUN="runuser -u postgres --"; chown postgres "$WORK"; else RUN=""; fi
$RUN "$BIN/initdb" -D "$WORK/data" -U postgres -A trust >/dev/null
$RUN "$BIN/pg_ctl" -D "$WORK/data" -o "-p $PORT -k $WORK -c listen_addresses=''" -l "$WORK/log" start >/dev/null
PSQL=(psql -h "$WORK" -p "$PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -q)
"${PSQL[@]}" -f "$HERE/local_stub.sql"
DSN="host=$WORK port=$PORT user=postgres dbname=postgres"
pf() { python3 "$ROOT/supabase/scripts/preflight.py" "host=$WORK port=$PORT user=postgres dbname=$1" >"$WORK/pf.txt" 2>&1; echo $?; }
echo "preflight: fresh Supabase-shaped database";  [ "$(pf postgres)" = 0 ] || { cat "$WORK/pf.txt"; echo "FAIL preflight should accept a fresh database"; exit 1; }
for case in foreign_schema trgm_public; do
  "${PSQL[@]}" -c "create database $case"
  psql -h "$WORK" -p "$PORT" -U postgres -d "$case" -v ON_ERROR_STOP=1 -q -f "$HERE/local_stub.sql"
done
psql -h "$WORK" -p "$PORT" -U postgres -d foreign_schema -q -c "create schema solvant; create table solvant.customers(id int);"
psql -h "$WORK" -p "$PORT" -U postgres -d trgm_public -q -c "create extension pg_trgm schema public;"
[ "$(pf foreign_schema)" = 1 ] && grep -q "NOT created by this app" "$WORK/pf.txt" || { cat "$WORK/pf.txt"; echo "FAIL preflight must reject a foreign solvant schema"; exit 1; }
echo "preflight: rejects a foreign 'solvant' schema"
[ "$(pf trgm_public)" = 1 ] && grep -q "pg_trgm installed in schema public" "$WORK/pf.txt" || { cat "$WORK/pf.txt"; echo "FAIL preflight must reject pg_trgm outside extensions"; exit 1; }
echo "preflight: rejects pg_trgm installed outside 'extensions'"
python3 "$ROOT/supabase/scripts/preflight.py" "$DSN" --expect-ref someotherproject >/dev/null && { echo "FAIL wrong project ref accepted"; exit 1; }
echo "preflight: rejects a connection string for another project"
for f in "$ROOT"/supabase/migrations/*.sql; do echo "apply $(basename "$f")"; PGOPTIONS="-c client_min_messages=warning" "${PSQL[@]}" -f "$f"; done
echo "single-transaction apply rolls back completely on failure"
"${PSQL[@]}" -c "create database partial"
psql -h "$WORK" -p "$PORT" -U postgres -d partial -v ON_ERROR_STOP=1 -q -f "$HERE/local_stub.sql"
cat "$ROOT"/supabase/migrations/*.sql > "$WORK/all.sql"; echo "select 1/0;" >> "$WORK/all.sql"
PGOPTIONS="-c client_min_messages=warning" psql -h "$WORK" -p "$PORT" -U postgres -d partial -v ON_ERROR_STOP=1 -q -1 -f "$WORK/all.sql" >/dev/null 2>&1 && { echo "FAIL injected error not raised"; exit 1; }
[ "$(psql -h "$WORK" -p "$PORT" -U postgres -d partial -At -c "select count(*) from pg_namespace where nspname='solvant'")" = 0 ] || { echo "FAIL partial migration left objects behind"; exit 1; }
echo "  ok: nothing left behind after an injected failure"
[ "$(pf postgres)" = 0 ] || { cat "$WORK/pf.txt"; echo "FAIL preflight should accept this app's own schema"; exit 1; }
echo "preflight: accepts this app's own schema (re-apply)"
"${PSQL[@]}" -c "create table solvant.unexpected(id int)"
[ "$(pf postgres)" = 1 ] || { echo "FAIL preflight must reject foreign objects inside solvant"; exit 1; }
"${PSQL[@]}" -c "drop table solvant.unexpected"
echo "preflight: rejects foreign objects inside 'solvant'"
echo "re-apply (idempotency)"; for f in "$ROOT"/supabase/migrations/*.sql; do PGOPTIONS="-c client_min_messages=warning" "${PSQL[@]}" -f "$f"; done
set -o pipefail
"${PSQL[@]}" -t -A -f "$HERE/rls_test.sql" 2>&1 | sed 's/^psql:[^ ]* NOTICE:  /  /' | grep -vE '^\s*$'
echo "recovery script refuses to drop a schema that holds application data"
"${PSQL[@]}" -f "$ROOT/supabase/recovery/remove_empty_solvant_schema.sql" >/dev/null 2>&1 && { echo "FAIL recovery dropped a schema with data"; exit 1; }
[ "$(psql -h "$WORK" -p "$PORT" -U postgres -d postgres -At -c "select count(*) from solvant.opportunities")" -gt 0 ] || { echo "FAIL data lost"; exit 1; }
echo "  ok: refused, data intact"
cat "$ROOT"/supabase/migrations/*.sql > "$WORK/all.sql"
PGOPTIONS="-c client_min_messages=warning" psql -h "$WORK" -p "$PORT" -U postgres -d partial -X -v ON_ERROR_STOP=1 -q -1 -f "$WORK/all.sql" >/dev/null
PGOPTIONS="-c client_min_messages=warning" psql -h "$WORK" -p "$PORT" -U postgres -d partial -X -v ON_ERROR_STOP=1 -q -f "$ROOT/supabase/recovery/remove_empty_solvant_schema.sql" >/dev/null
[ "$(psql -h "$WORK" -p "$PORT" -U postgres -d partial -At -c "select count(*) from pg_namespace where nspname='solvant'")" = 0 ] || { echo "FAIL empty install not removed"; exit 1; }
echo "  ok: empty first install removed cleanly; nothing outside 'solvant' touched"
echo "ALL DATABASE CHECKS PASSED"
