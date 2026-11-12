# Solvant Signal Engine — platform

A private web application for finding, qualifying and tracking commercial opportunities for Solvant.io. It reuses the
tested Python discovery and qualification engine (`poc/signal_engine`) and stores everything in the dedicated Supabase
project `dfnaevcsergsphiiodtm`.

## Architecture

| Part | Where | What it does |
|---|---|---|
| Web app | `web/` (Next.js 16, App Router, Tailwind) | Dashboard, opportunity list and detail pages, kanban pipeline, intake, follow-ups, saved searches, notifications, analytics, source control centre, settings |
| Engine function | `web/api/engine.py` (Vercel Python function) | Runs the **same** Python engine (copied to `web/api/_engine` by `scripts/sync_engine.py`; PR checks fail if the copy is stale) to parse alert e-mails, CSVs and pasted posts, and classify them |
| Database | `supabase/migrations/*.sql` | 23 tables, RLS on every table, audited functions, hashed ingest tokens |
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

## Deployment (owner actions, no local installs)

### 1. Apply the database migrations

The Supabase connection available to Claude is **read-only**, so the migrations have not been applied yet. Choose one of these options:

**Option A, GitHub Actions (recommended):**
1. In Supabase, open **Project dfnaevcsergsphiiodtm → Connect → Session pooler** and copy the connection string, including the database password.
2. In GitHub, open **rekuom/Solvant-Lead-Enginer → Settings → Secrets and variables → Actions → New repository secret** and add `SUPABASE_DB_URL` with that value.
3. Open **Actions → Apply database migrations → Run workflow**, type `APPLY` and run it. It rehearses the migrations on a throwaway Postgres first, then applies them, each file in a single transaction.

**Option B, SQL editor:** open the Supabase **SQL editor** and run the four files in `supabase/migrations/` in order.

All four migrations are non-destructive. They only create objects and never drop or overwrite existing data.

### 2. Create your admin access

In the Supabase SQL editor, run:

```sql
select public.create_bootstrap_code();
```

Copy the code. It expires in 7 days and works once. You'll use it in step 4.

### 3. Configure Auth

In **Supabase → Authentication → URL configuration**:
- set the **Site URL** to the app URL from step 4;
- add `<app URL>/auth/callback` to **Redirect URLs**.

Once you have created your own account, consider disabling public sign-ups (**Authentication → Providers → Email**). Accounts without a membership can't see any data either way.

### 4. Deploy the web app (Vercel)

1. In Vercel, choose **Add New → Project** and import `rekuom/Solvant-Lead-Enginer`.
2. Set **Root Directory** to `web`.
3. Add the environment variables:
   - `NEXT_PUBLIC_SUPABASE_URL` = `https://dfnaevcsergsphiiodtm.supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` = the project's publishable or anon key
4. Deploy.

**Plan note:** Vercel's Hobby plan is for non-commercial use, so a business deployment normally needs a paid plan. This is your decision.

### 5. Sign in

Open the app, create your account, confirm your e-mail, then enter the setup code from step 2. You become admin.

### 6. Connect the collectors (optional)

1. In the app, open **Settings → Discovery connection → Create token**.
2. In GitHub, add the secret `SIGNAL_INGEST_TOKEN` and the variables `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
3. Optional: set the variable `DISCOVERY_SCHEDULE_ENABLED=true` for daily collection from free sources (06:17 UTC).

### 7. Inbound e-mail (optional, needs a provider)

Point the provider's inbound webhook at `<app URL>/api/engine/inbound-email`. It must send the raw message and the header `X-Signal-Token: <inbound_email token>`. Choosing and paying for a provider is your decision.

## Tests

| Suite | Command | Covers |
|---|---|---|
| Python | `cd poc && python -m unittest discover -s tests` | Engine, intake, Brave non-retention, privacy, policy, engine API |
| Database | `bash supabase/tests/run_local.sh` | 41 RLS and behaviour checks; migrations re-apply cleanly |
| Web | `cd web && npm test && npm run typecheck && npm run build` | Filters, CSV safety, types, production build |

All of these run in `.github/workflows/pr-checks.yml`, with no secrets.
