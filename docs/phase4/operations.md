# Operations guide: first real buyer validation

## 1. Brave Search API key (only when you decide to test it)

**What the adapter does**, checked against Brave's API reference on 2026-11-06:
- `GET https://api.search.brave.com/res/v1/web/search`
- header `X-Subscription-Token`
- parameters `q`, `country`, `search_lang`, `count=20`, `freshness`, `spellcheck=0`, `safesearch=moderate`
- reads `web.results[].url / title / description / age`

`country` only accepts Brave's documented list (about 35 countries plus `ALL`). The UAE, Ireland, Romania and Czechia therefore use `country=ALL` plus a location word in the query ("Dubai", "Ireland", "România", "Česko").

**Before you add a key, know Brave's storage terms.** Brave's help page says the *Data for Search* and *Data for AI* plans **do not permit retaining any part of the API output**; only a *storage rights* plan does. So by default the engine:
- processes Brave results only during the run;
- publishes **counts only** (by market and intent category);
- verifies a result against its original source only where that source has a permitted API (GitHub today). The verified record is then the source's data, not Brave's.

Tick `brave_retention_permitted` only if your plan includes storage rights.

**Setup (you do this; I didn't sign up or buy anything):**
1. Create a Brave Search API account and choose a plan. A card is required, and pricing is metered.
2. Copy the API key.
3. In GitHub, open **rekuom/Solvant-Lead-Enginer → Settings → Secrets and variables → Actions → New repository secret**. Name it `BRAVE_SEARCH_API_KEY` and paste the key as the value.
4. The key is read only by the *Discover* step, and only when `enable_brave` is ticked. It is never written to logs or artifacts.

**Safety rails:**
- Without the tick, the workflow only *plans*: 100 queries, estimated cost about $0.50 at $0.005 per request (estimate).
- The hard cap is 100 requests per run.
- Requests are weighted: explicit hire requests 30, provider searches 20, recommendations 15, agency partnerships 15, freelance hiring 10, pain/blockers 10.
- They're spread across UK, UAE, Ireland and 16 European markets in 14 languages.
- Snippets are always `search_snippet_only` and go to Pipeline H, never counted as buyers.

## 2. Marketplace alerts → intake

All of these routes are **user-initiated**:
- you receive alerts in your own account;
- you forward or export them to a private mailbox or folder;
- you import them with `intake`.

No scraping, no automated proposals, and no contact outside the platform. Imported records are `user_submitted` until you open the original URL and confirm it.

| Platform | How to get alerts (verify in your account; menus change) | Import | Rules the engine applies |
|---|---|---|---|
| **Upwork** | Upwork's help says **instant job alerts need Freelancer Plus**: bell icon → Notifications → *Job alerts* → alert preferences (email/app). Saved searches show on your job feed. RSS ended 20 Aug 2024. | Save the alert e-mail as `.eml`, then `intake email file.eml` | Proposal in-platform only (Connects). Off-platform contact never assumed |
| **Freelancer.com** | Settings → *Email & Notifications* → enable new projects matching your skills (third-party guide; confirm in your account) | `intake email` (digests are split per project) | In-platform bids only |
| **PeoplePerHour** | No freelancer alert feature could be confirmed from official pages. Check *Settings → Notifications*; otherwise copy project URL and text manually | `intake add --source-key peopleperhour …` or `intake email` | In-platform proposals |
| **Malt** | Notification centre at `malt.<country>/account/notifications`. Malt sends at most **7 matched opportunities per 7 days** | `intake email` | In-platform; agency status unknown |
| **Fiverr Briefs** | Matched briefs arrive on the *Briefs* page ("Your matches") and by e-mail; 72-hour response window | `intake email` (e-mail) or `intake add` (paste) | In-platform offer only |
| **Bark** (if you ever buy credits) | Leads in your Bark dashboard | `intake csv` → stored as `licensed_import` (Pipeline G) with acquisition cost | Respond via Bark per its terms |

**Examples:**
```bash
cd poc
python3 -m signal_engine.discovery.run intake email ~/alerts/upwork-2026-11-07.eml
python3 -m signal_engine.discovery.run intake add --source-key peopleperhour --url https://www.peopleperhour.com/freelance-jobs/... \
   --post-date 2026-11-07 --text "pasted project description" --budget "£500"
python3 -m signal_engine.discovery.run report
```
Synthetic examples of each alert type are in [`poc/fixtures/alerts/`](../../poc/fixtures/alerts/). Import them only with `--fixture`; they're stored as `fixture` and never become leads.

**Where to run intake:** on your own computer or a private environment. Intake data is personal; don't run it in GitHub Actions of this **public** repository.

## 3. What disappears and what persists

| Data | Where | Lifetime | Personal data? |
|---|---|---|---|
| `raw_discovered.jsonl`, `opportunities_private.jsonl`, review packets | Actions runner (`poc/out/discovery/`) | **Deleted when the job ends** | Yes (excerpts, hashed authors) — never uploaded |
| Intake store `poc/out/private/intake.jsonl` | Wherever you run intake | Until you delete it (git-ignored) | Yes — keep private |
| Redacted reports (`report_public.*`, `stage_audit.json`, `run_log.json`) | Actions **artifact** | **30 days**; downloadable by any signed-in user while the repo is public | No: actionable pipelines only, no handles, PII-redacted. Brave records only with storage rights |
| Job summary | Actions run page | Per the repo's log retention (default 90 days); public | Same redacted content |
| Query log (repeat prevention) | Actions cache | Evicted after ~7 days unused | No (query ids and counts) |
| Opportunities "saved permanently" | — | **Nowhere yet.** No database is connected. Nothing is permanently saved until private storage is approved | — |

## 4. Proposed private storage (design only; not applied)

**Target:** the dedicated Solvant Supabase project `dfnaevcsergsphiiodtm`, schema `signal` ([`supabase-schema-proposal.sql`](supabase-schema-proposal.sql)).

**Path:**
1. GitHub Actions → an **Edge Function `ingest-opportunities`**, authenticated with a dedicated ingest secret (repository secret). There's no service-role key in Actions.
2. The function validates the payload (schema, `https://` URLs, verification state, permitted source) and inserts into `signal.evidence_records` and `signal.opportunities` only.
3. RLS: no anonymous access. Reviewers and sales read through Supabase Auth roles.
4. Retention: `retain_until`, plus deletion handling (purge the excerpt when the source is deleted or someone objects).
5. Only records in pipelines A, B, C, E and G are sent. Research and excluded records stay as counts.
6. Intake from your own machine goes through the same function (CLI flag), so personal data never touches the public repository.

**Approval needed for:** applying the migration, creating the Edge Function, and adding the ingest secret.

## 5. First operational run (after the PR is merged)

**A. Discovery workflow:** Actions → **Multi-source discovery** → Run workflow:

| Input | Recommended first value | Why |
|---|---|---|
| sources | `github_issues,feeds,search:brave` | GitHub live; feeds (none registered, reported as skipped); Brave plans only unless enabled |
| since_days | `30` | Fresh requests only |
| max_requests | `20` | GitHub budget per connector (search limit 30/min with the job token) |
| include_discussions | ✅ | First real test of GitHub Discussions (GraphQL) |
| allow_restricted | *(empty)* | HN, Reddit, n8n, Make and social stay off until reviewed |
| dry_run | ☐ | |
| enable_brave | ☐ until the key exists; then ✅ | |
| brave_max_requests | `100` | Hard cap |
| brave_freshness | `pm` | Last 31 days |
| brave_retention_permitted | ☐ unless your plan has storage rights | |

**B. Procurement comparison:** Actions → **Live lead validation** → Run workflow (`days=30`, `max_records=100`). Kept separate, Pipeline E.

**C. Read the results:** open the run's *Summary* for the per-source table (records found, verified, genuine requests, Direct SME, freelance, agency, contact routes, failed requests, estimated cost, runtime) and the A/B/C sections. Download `discovery-<run id>` for the redacted CSV.

**D. Review:** false positives aren't estimated automatically. Once at least 20 items exist in A/B/C (alerts plus discovery), run `review-packet` locally and have a person label it blind.

## 6. Commercial assessment

| Source | Realistic for leads? | Evidence |
|---|---|---|
| Marketplace alerts (Upwork, Freelancer, Malt, Fiverr, PPH) | **Yes, the most realistic** today: explicit, budgeted, current projects. Competitive and in-platform only | Platform design; mechanism tested on fixtures; **no real alerts imported yet** |
| Manual capture (LinkedIn, groups, forums) | **Yes for UK/UAE founder-led SMEs**; costs time | Mechanism tested; no captures yet |
| Brave Search | **Maybe**: finds public requests across sites, but results are snippets (H) and storage is restricted by plan | Not run (no key) |
| GitHub | **Weak** | 0 buyers in 133 real records |
| Tenders | Real but formal and large; a separate channel | Phase 3 held-out: 14 of 15 surfaced relevant |
| HN, n8n, Make boards | Promising but gated | Built; permission or terms review pending |
