# Live acceptance tests (real deployment)

Unit tests, the local database harness and the engine-endpoint tests run against **local doubles**. They are not evidence that the deployed system works. A row below counts as passed only when it has been executed against the **real** Supabase project and the **real** Vercel deployment, and its observed result has been recorded.

**Rules:**
- Use only real leads you are entitled to store. Never put synthetic records into production; the app refuses the repository fixtures anyway.
- Never paste passwords, tokens or connection strings into chat, issues or logs.
- Where a check needs a second identity, use a second real account that has **no** membership.

Record the date, tester, result and a screenshot or response code for each row.

## A. Database security on the real project (Supabase SQL editor)

These checks simulate API roles inside a transaction that is **rolled back**, so nothing is changed. Replace `<owner-uuid>` with your user id after step 9, from **Authentication → Users**.

```sql
begin;
-- A1 anonymous: no table access
set local role anon;
select count(*) from solvant.opportunities;          -- expected: ERROR permission denied
rollback;

begin;
-- A2 signed in but not a member: sees nothing
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-000000000001","role":"authenticated"}';
select count(*) from solvant.sources;                 -- expected: 0
select solvant.save_intake('{"origin":"manual"}', '[]'); -- expected: ERROR not allowed
rollback;

begin;
-- A3 owner (after claiming admin): sees data, cannot edit source facts directly
set local role authenticated;
set local request.jwt.claims = '{"sub":"<owner-uuid>","role":"authenticated"}';
select count(*) from solvant.sources;                 -- expected: 41
update solvant.opportunities set body_excerpt = 'x';  -- expected: ERROR permission denied
rollback;

-- A4 advisors: Database → Advisors → Security: expected no errors for schema solvant
```

## B. End-to-end checklist (browser, phone and smoke script)

| # | Test | How | Expected |
|---|---|---|---|
| B1 | Endpoint routing | `python3 scripts/smoke_test.py --base-url https://<app>` | health 200; intake 401 with `X-Solvant-Endpoint: intake`; inbound-email 401; intake GET 405 |
| B2 | Authentication | Sign up, confirm e-mail, sign in, sign out, sign in on a phone | Session persists; signed-out visitors are redirected to /login |
| B3 | Non-member denial | Sign in with the second account (no role) | "Access pending" page; smoke script `SMOKE_NONMEMBER_JWT` checks pass |
| B4 | Admin claim | Enter the one-time code from `solvant.create_bootstrap_code()` | Becomes admin; reusing the code fails |
| B5 | Manual lead creation | Add leads → paste a real public post you may store | Record opens with pipeline, intent and evidence; verification "Unverified" |
| B6 | Marketplace alert upload | Upload a real alert `.eml` from your own account | One record per project; in-platform contact rule shown; the file isn't stored |
| B7 | Classification persistence | Sign out, sign in on another device and open the record | Same classification, evidence and history |
| B8 | Duplicate ingestion | Submit the same URL again; submit the same text under another URL | First is reported "already known (updated)"; second is flagged duplicate |
| B9 | Lead detail rendering | Open the detail page on desktop and phone | Source facts and engine interpretation shown separately; confidence and history visible |
| B10 | Classification correction | Correct the pipeline with a reason | New current classification; previous one still listed in the history |
| B11 | Pipeline stage updates | Drag the card to Contacted, then Won with a value | Activity log shows each change; dashboard funnel counts update |
| B12 | Follow-up creation | Add a follow-up due in 1 minute, then reload | Appears in Follow-ups and Notifications |
| B13 | Source enable/disable | Enable `github_issues` (permitted); try to enable `gitlab_issues` (unknown) | First saves; second is blocked with an explanation |
| B14 | CSV export restrictions | Export a list containing a tender plus a marketplace/LinkedIn lead | CSV contains the tender only; the `X-Export-Withheld-Restricted` header counts the rest; audit log has an `export` row |
| B15 | Collector ingestion | Settings → create token → GitHub secret and variables → run **Multi-source discovery** with `sources=auto` | Plan step lists RUN/skip reasons; records appear; Sources page shows the run and "Automated collection active" |
| B16 | Persistence after new session | Repeat B7 the next day | Unchanged |
| B17 | Deleted/expired evidence | On a test record that is yours to delete: as admin, set `retain_until` in the past (SQL editor), then Settings → "Remove expired excerpts now" | Excerpt, linked evidence and derived snippets gone; history kept; audit has a `retention` row |
| B18 | Secret and private-data leakage | Inspect the Actions logs, job summary and artifacts of B15; view page source of the app; check the Vercel function logs | No tokens, connection strings or lead text; artifacts contain only redacted, privacy-gated reports |

## C. What does NOT count

- Mocked Supabase responses in `poc/tests/test_engine_api.py`.
- The local Postgres harness (`supabase/tests/run_local.sh`).
- Any check marked **SKIP** by `scripts/smoke_test.py`.

These prove the code paths, not the live integration.
