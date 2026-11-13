# Solvant Signal Engine — platform

A private web application for finding, qualifying and tracking commercial opportunities for Solvant.io. It reuses the
tested Python discovery and qualification engine (`poc/signal_engine`) and stores everything in the dedicated Supabase
project `dfnaevcsergsphiiodtm`.

## Architecture

| Part | Where | What it does |
|---|---|---|
| Web app | `web/` (Next.js 16, App Router, Tailwind) | Dashboard, opportunity list and detail pages, kanban pipeline, intake, follow-ups, saved searches, notifications, analytics, source control centre, settings |
| Engine functions | `web/api/engine/*.py` + `web/pyengine/` | Run the **same** Python engine (copied by `scripts/sync_engine.py`; PR checks fail if the copy is stale) to parse alert e-mails, CSVs and pasted posts, and classify them |
| Database | `supabase/migrations/*.sql` | Schema `solvant`: 24 tables, RLS on every table, audited functions, hashed ingest tokens |
| Collectors | `.github/workflows/multi-source-discovery.yml` | GitHub Issues and Discussions, Contracts Finder, Find a Tender, TED, RSS/Atom and Brave (opt-in, counts only). Records are pushed to the database by `signal_engine.discovery.platform.push` |

**Data flow**
- **Browser intake:** the browser posts to `/api/engine/intake` with the user's session token. The engine function checks the session with Supabase Auth, parses and classifies the content, then calls `save_intake` **as that user**, so RLS applies.
- **Collectors:** GitHub Actions classifies records with the same engine and calls `ingest_records` with a hashed, scoped, revocable token.
- **Inbound e-mail:** a provider webhook posts to `/api/engine/inbound-email` with a token scoped to `inbound_email`, which then follows the same path.

**No service-role key is used anywhere.**

## Security model

- **Access:** no anonymous access to any table. Signing in is not enough; a user needs a `members` row (`admin`, `editor` or `viewer`).
- **First admin:** claimed once with a one-time setup code (`create_bootstrap_code()`). It's stored hashed, expires and works only once.
- **Protected fields:** source facts, verification and classification can't be edited directly (column-level grants). Changes go through `override_classification` (requires a reason and keeps the history), `verify_opportunity` and `mark_duplicate`, and each writes the activity and audit logs.
- **Rules enforced in the database:**
  - Brave output can never be stored (`opportunities_no_brave`).
  - Synthetic fixtures are refused.
  - Sources with unknown or prohibited permission can't be switched on for automated collection.
  - A paid source can't run without a monthly budget above zero (`sources_enable_guard`).
- **Engine function hardening:**
  - Repository fixtures are refused.
  - Size limits apply: 2 MB per e-mail or CSV, 3 MB per request.
  - Raw files are never stored.
  - Errors never echo submitted content.
- **Web hardening:**
  - Security headers: `X-Frame-Options DENY`, nosniff, HSTS, strict referrer, `noindex`.
  - CSV exports are protected against formula injection, include only sources whose terms allow export, and contain no excerpts.
- **Public repository:** no lead data in the repository, Actions logs or artifacts. Discovery artifacts are published only after the privacy gate passes, and the push step logs counts only.
- **Retention:** excerpts expire after `retention_days` (default 365) via `purge_expired_excerpts()`. Records, classifications and audit history remain.

## Opportunity pipelines

| Letter | Key | Meaning |
|---|---|---|
| A | `A_DIRECT_SME` | Direct SME buyers |
| B | `B_FREELANCE_PROJECT` | Freelance and project opportunities |
| C | `C_AGENCY_PARTNER` | Agency partnerships |
| D | `D_OPERATIONAL_PAIN` | Operational problems and potential demand |
| E | `E_PROCUREMENT` | Government and enterprise procurement |
| F | `F_RECRUITMENT_SIGNAL` | Employment and recruitment signals |
| G | `G_LICENSED_LEADS` | Purchased or licensed leads |
| H | `H_RESEARCH_UNVERIFIED` | Research and unverified |
| I | `GLOBAL_REVIEW` | Global and exceptional opportunities |
| J | `EXCLUDED` | Excluded or archived (kept for audit) |

Nothing is deleted for lacking evidence. Weak or uncertain records get priority C and stay in review.

## Database safety

- **Namespace:** every object lives in the app-owned schema **`solvant`** (plus `pg_trgm` in `extensions`). Nothing is created in `public`, so the generic table names can't collide with other objects.
- **Not "unconditionally non-destructive".** Inside `solvant` the migrations use `create or replace function`, `drop policy/trigger if exists` on their own tables, and `on conflict do update` for the source seed. That is why they must only ever run against a `solvant` schema that this app created.
- **Preflight (`supabase/preflight/preflight.sql`)** is read-only (`BEGIN READ ONLY`) and generated from the migrations. It returns **REJECT** if:
  - the database isn't a Supabase project;
  - the API roles are missing;
  - a `solvant` schema exists without this app's migration ledger;
  - `solvant` contains any object the migrations don't create;
  - the ledger has a version newer than this code;
  - `pg_trgm` is installed outside `extensions`.

  It also reports a WARN if `solvant` isn't yet exposed through the Data API. `supabase/scripts/preflight.py --expect-ref dfnaevcsergsphiiodtm` also refuses any connection string for another project.
- **Atomic apply:** the workflow concatenates all migrations and applies them with `psql -1`, so any error rolls everything back. This is tested locally with an injected failure.
- **Recovery:**
  - A failed apply leaves nothing behind.
  - To undo a successful first install that contains no data, use `supabase/recovery/remove_empty_solvant_schema.sql`. It refuses if any application rows exist.
  - After real data exists, recovery means restoring a backup. See step 4 below.
- **Ledger:** `solvant.schema_migrations` records every applied version.

## Supabase keys

- **Web app:** use the modern **publishable key** (`sb_publishable_…`) as `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. The legacy anon JWT is accepted as `NEXT_PUBLIC_SUPABASE_ANON_KEY` as a fallback. All data access runs with the signed-in user's own JWT.
- **Python engine:** `signal_engine/discovery/platform/rest.py` sends the publishable key **only** in the `apikey` header; per Supabase's docs, a publishable key in `Authorization: Bearer` is rejected because it isn't a JWT. The user's real JWT goes in `Authorization` for user requests. Machine ingestion sends only `apikey`; its authority is the hashed, scoped ingest token. A legacy anon JWT is mirrored into `Authorization` for compatibility, and a `sb_secret_` key is refused outright.
- **No secret or service-role key anywhere.**

## Engine endpoint routing

There are no rewrites. Each endpoint is its own Vercel Python function, and its operation is fixed in the file, so the request path can't misroute it:
- `web/api/engine/health.py` → `GET /api/engine/health`
- `web/api/engine/intake.py` → `POST /api/engine/intake`
- `web/api/engine/inbound-email.py` → `POST /api/engine/inbound-email`

The shared code and the copied engine live in `web/pyengine/`, bundled with `includeFiles`. Every response carries an `X-Solvant-Endpoint` header. `scripts/smoke_test.py` uses it to prove each URL reached the right function on the real deployment.

## Export permissions

A CSV row is exported only if the **source's contractual export right** is recorded:
- `sources.export_allowed` must be set, together with an `export_basis` of at least 10 characters (enforced by the `sources_export_guard` constraint);
- this is impossible for sources whose terms are unknown or prohibited;
- **purchased leads** also need an explicit per-record licence (`licence_allows_export=yes` in the import CSV).

Verification status and "we entered it ourselves" never grant export.

**Defaults:** only public procurement notices are exportable (UK Open Government Licence / EU open data). Marketplaces, social sources and lead vendors start as not exportable; an admin can record a basis on the Sources page. Withheld rows are counted, never listed, and every export is written to the audit log.

## Collector control (Sources page → GitHub Actions)

The `multi-source-discovery` workflow calls `solvant.collector_plan` with the discovery token. It then runs `signal_engine.discovery.platform.plan`, which selects a source only if all of these hold:
- the engine has a connector for it;
- the registry permits it: either `permitted`, or `restricted` with a recorded approval. Unknown, prohibited, manual-only and licensed terms can't be overridden;
- an admin has enabled it;
- its own cron schedule is due (scheduled runs are evaluated hourly);
- for paid sources: a manual run only, with a budget above zero, enough remaining budget and the credential present; requests are capped by the remaining budget;
- it is within its per-run request limit.

If the plan can't be fetched, **scheduled runs collect nothing**, and the Sources page shows "Automated collection NOT active" until a collector has read the settings within the last 26 hours.

## Retention

| Data | Rule (when the policy is enabled) |
|---|---|
| Excerpts on records past `retain_until` that never progressed (discovered / needs review / archived) | Removed |
| Linked evidence copies (`evidence.source_fact`) | Removed |
| Derived evidence snippets in classifications | Removed; values, confidence and history kept |
| Verification notes inside activity entries | Removed; the activity entry is kept |
| Records that progressed into sales | Kept (active business records) |
| Audit log | Deleted after `audit_days` (default 730) |
| Read notifications | Deleted after 90 days |

`solvant.enforce_retention()` is a **no-op until `retention_policy.enabled = true`**. To run it daily, apply `supabase/optional/enable_retention_schedule.sql` (pg_cron) after the rules are approved. Admins can also run the same rules manually on the Settings page.

## Deployment order (owner actions; no local installs)

1. **Review PR #2 and let CI pass.**
2. **Read-only preflight against the target.** In the Supabase SQL editor of project `dfnaevcsergsphiiodtm`, paste and run `supabase/preflight/preflight.sql`. The VERDICT row must be `OK`; a `WARN` for Data API exposure is expected before step 6. It changes nothing.
3. **Merge PR #2.** The migration workflow added by this PR can only be started from the default branch after the merge.
4. **Backup / recovery point.**
   - Paid plans: confirm daily backups or PITR in **Database → Backups**.
   - Free plan: there are no downloadable backups. The project currently holds no app data, so the recovery path is the single-transaction apply plus `supabase/recovery/remove_empty_solvant_schema.sql`.
5. **Apply the migrations,** using one of:
   - **Workflow (recommended):** add the repository secret `SUPABASE_DB_URL`. Use the **Session pooler** URI from Supabase → Connect, in exactly this form: `postgresql://postgres.dfnaevcsergsphiiodtm:<password>@<region>.pooler.supabase.com:5432/postgres`. The username must include `.dfnaevcsergsphiiodtm`; plain `postgres` is rejected. Port 6543 (the Transaction pooler) and the direct `db.<ref>.supabase.co` host are also rejected. URL-encode special characters in the password. The workflow validates the format before connecting and never prints it, then run **Actions → Apply database migrations** and type `APPLY`. It rehearses locally, runs the preflight against the target, applies everything in one transaction and runs the preflight again. The connection string is masked and never printed.
   - **SQL editor:** paste the four files in `supabase/migrations/` as one script inside `begin; … commit;`.
6. **Expose the schema and verify Auth and RLS.**
   - Add `solvant` under **Project Settings → Data API → Exposed schemas**.
   - In **Authentication → URL configuration**, set the Site URL and the redirect URL `<app>/auth/callback`.
   - Run the RLS checks in `docs/platform/acceptance-tests.md` §A.
7. **Deploy the web app (Vercel).**
   - Root directory: `web`.
   - Environment variables: `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.
   - Plan choice: the Hobby plan is non-commercial.
8. **Run the live smoke tests:** `scripts/smoke_test.py --base-url <app>` (endpoint routing and denial checks), then the checklist in `acceptance-tests.md`.
9. **Create the first administrator.** Run `select solvant.create_bootstrap_code();` in the SQL editor. Sign up in the app, confirm your e-mail and enter the code. Then turn off public sign-ups.
10. **Connect discovery.**
    - In **Settings → Discovery connection**, create a token.
    - Add the GitHub secret `SIGNAL_INGEST_TOKEN` and the variables `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`.
    - Enable sources on the Sources page.
    - Set `DISCOVERY_SCHEDULE_ENABLED=true`.
11. **Small real-data test.** Run **Multi-source discovery** manually (`sources=auto`) with a few sources and a low request limit. Check the records, the source health and the absence of leaks before you enable schedules widely.

Never put database passwords in chat, logs or files. The migration workflow refuses any connection string that isn't for `dfnaevcsergsphiiodtm`.

## Tests

| Suite | Command | Covers |
|---|---|---|
| Python | `cd poc && python -m unittest discover -s tests` | Engine, intake, Brave non-retention, privacy, policy, engine API |
| Database | `bash supabase/tests/run_local.sh` | RLS/behaviour checks, export guard, retention, preflight accept/reject cases, single-transaction rollback, recovery script |
| Web | `cd web && npm test && npm run typecheck && npm run build` | Filters, CSV safety, types, production build |

All of these run in `.github/workflows/pr-checks.yml`, with no secrets.
