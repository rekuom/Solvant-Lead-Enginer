#!/usr/bin/env bash
# Builds the app against the local stand-ins and runs the real-browser redirect-flow test.
set -euo pipefail
cd "$(dirname "$0")/.."
export NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:4601 NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_e2e_placeholder
export SUPABASE_SECRET_KEY=sb_secret_e2e_test_value_only SOLVANT_PUBLIC_HOST=localhost:3100
export MICROSOFT_CLIENT_ID=e2e-client MICROSOFT_CLIENT_SECRET=e2e-secret
export MICROSOFT_AUTHORITY_URL=http://127.0.0.1:4602/oauth MICROSOFT_GRAPH_URL=http://127.0.0.1:4602/graph
rm -rf .next && npx next build >/tmp/e2e-build.log 2>&1 || { tail -30 /tmp/e2e-build.log; exit 1; }
(npx next start -p 3100 >/tmp/e2e-server.log 2>&1 &) ; sleep 4
trap 'pkill -f "next start -p 3100" || true' EXIT
node e2e/oauth-flow.mjs
