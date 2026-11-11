"""Bridge between the discovery/qualification engine and the Solvant platform (Supabase).

items.py   Opportunity -> flat platform item (the payload accepted by public.ingest_records / public.save_intake)
intake.py  browser / inbound-email intake: parse, validate, classify (pure functions, no I/O)
rest.py    tiny stdlib client for Supabase PostgREST RPC calls
push.py    CLI used by GitHub Actions to push a discovery run into the private database (counts-only logging)
"""
ENGINE_VERSION = "rules-2026.11"
