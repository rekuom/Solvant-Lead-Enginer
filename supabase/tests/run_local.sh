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
for f in "$ROOT"/supabase/migrations/*.sql; do echo "apply $(basename "$f")"; PGOPTIONS="-c client_min_messages=warning" "${PSQL[@]}" -f "$f"; done
echo "re-apply (idempotency)"; for f in "$ROOT"/supabase/migrations/*.sql; do PGOPTIONS="-c client_min_messages=warning" "${PSQL[@]}" -f "$f"; done
set -o pipefail
"${PSQL[@]}" -t -A -f "$HERE/rls_test.sql" 2>&1 | sed 's/^psql:[^ ]* NOTICE:  /  /' | grep -vE '^\s*$'
