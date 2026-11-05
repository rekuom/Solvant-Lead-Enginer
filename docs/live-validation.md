# Live lead validation (GitHub Actions)

Workflow: [`.github/workflows/live-lead-validation.yml`](../.github/workflows/live-lead-validation.yml), manual (`workflow_dispatch`) only.
Status: **ready to run. No live leads have been collected yet.** Counts appear only after the GitHub-hosted run.

## Business rules in force (from 2026-11-05)

| Rule | Implementation |
|---|---|
| **Markets:** UK, UAE and **all of Europe** (EU and non-EU, including Switzerland, Norway, Iceland, the Balkans, the microstates, Ukraine and Moldova) | [`markets.py`](../poc/signal_engine/markets.py). Configurable `TARGET_MARKETS`. Turkey, Georgia, Armenia and Azerbaijan are included and flagged `transcontinental`. Russia and Belarus are included and flagged `sanctions_review` |
| **Location comes from place evidence only** | Structured country codes on the notice (TED `buyer-country`, the source's jurisdiction), then country, alias or city names in the text. Currency is never used. Ambiguous words (Reading, Nice, Turkey-the-bird, Georgia-the-US-state) are not treated as places |
| **Unknown location → review**, never auto-excluded | Tier A/B with unknown location → Priority B with `location unknown: review` |
| **Explicit non-target location → excluded** | e.g. "Ohio, USA" |
| **No minimum or maximum budget** | Budget is stored as `budget_stated` (verbatim), `budget_kind` and a rough `budget_gbp_estimate`. It is never a reason for exclusion or downgrade |
| **Large or complex work is flagged, not rejected** | `complexity` (low / medium / high), `delivery_flags` (security clearance, certification, on-site, language, framework/DPS, insurance, named enterprise platform, formal bid), `partnership_opportunity` (value ≥ £100k equivalent, framework, consortium/subcontract wording, product tender) |
| **Safeguards kept** | Vendor adverts, employment ads, unrelated or physical automation, closed or outdated items and synthetic data are excluded. Search-index titles are never verified buyers |
| **Services in scope** | AI development and implementation, AI agents, n8n / Make / Zapier / Power Automate, CRM, finance / accounting / invoicing, document processing and data extraction, workflow automation, systems integration. Suggestions carry **no price** |

## Queues (CSV `queue` column and Markdown sections)

| Queue | Meaning |
|---|---|
| **Priority A — Immediate** | Verified content, published ≤ 30 days ago, explicit request for an external provider (Tier A/B), target market confirmed, not closed, permitted contact route |
| **Priority B — Promising** | Verified Tier A/B intent with something missing: location unknown, 31–90 days old, date unknown, open status unknown, or contact route unconfirmed |
| **Priority C — Potential** | Verified, specific operational problem with no explicit request to hire (Tier C) |
| Watchlist | Verified Tier D: general interest, product-only tender or partner channel |
| Excluded | Vendor, employment ad, unrelated or physical automation, closed, more than 90 days old, explicit non-target market, synthetic |
| Unverified | Search-index titles. **Never counted** |

## Source permissions (automated collection)

| Source | Status | Basis |
|---|---|---|
| UK Contracts Finder (OCDS API) | **Permitted — enabled** | Open Government Licence v3.0; documented API; no robots.txt |
| UK Find a Tender (OCDS API) | **Permitted — enabled** | Open Government Licence v3.0; official API documentation |
| EU TED (Search API v3) | **Permitted — enabled** | TED legal notice allows commercial reuse with credit; anonymous search access. *First live run confirms field names.* |
| n8n Community – Jobs | **Blocked — disabled** | Terms not reviewed by a person; no permission for commercial collection. The workflow archives `/tos` and `robots.txt` (one GET each) so a person can review them |
| Make Community – Hire a Pro | **Blocked — disabled** | Same as n8n |

Enforcement is in two places:
1. `validate.cmd_discover` skips any collector the registry ([`sources.py`](../poc/signal_engine/sources.py)) doesn't permit, and logs `permission_not_obtained`.
2. Each forum collector calls `sources.require(...)` and refuses to make a request. Candidate re-verification follows the same rule.

Tests cover both.

**To enable a forum:** get written permission (or a terms clause that allows automated commercial collection), record it in `sources.py` (basis, evidence, date), set `collection_permitted=True`, and update the test `PermissionTests.test_registry`.

## Limits and privacy

- **Request caps per run:** Contracts Finder 11 keyword searches; Find a Tender 5 pages; TED 2 POST pages of 50. At least 2–3 seconds between requests to the same host.
- **Records:** at most `max_records` verified records are kept (default 100), most actionable first. The number dropped is reported.
- **Personal data:** excerpts are stripped of emails, phone numbers and labelled contact names ("Contact: Jane Smith"). Forum handles are never written to reports. The job summary shows only titles, organisations, countries and URLs, with no excerpts.
- **No credentials, Supabase, paid APIs, outreach or schedule.** Checkout runs without persisted credentials and the job has `contents: read` only.

## How to run

1. Open https://github.com/rekuom/Solvant-Lead-Enginer/actions.
2. In the left sidebar, click **Live lead validation**.
3. Click **Run workflow** (right side). Keep branch `claude/trusting-hawking-kqus6b`, optionally change **days** (1–90, default 30) and **max_records** (1–200, default 100), then click the green **Run workflow** button.
4. Open the run when it finishes (usually 2–4 minutes). The **Summary** tab shows the permissions table, queue counts and the Priority A/B tables. At the bottom, the **Artifacts** section has `live-lead-report-<run id>` with:
   - `lead_report.csv`
   - `lead_report.md`
   - `funnel.json`
   - `leads.jsonl`
   - the fetch logs
   - `permission-review/` (forum terms pages)

## After the first run

- Check `discover_log.jsonl` for TED's `sample_keys` and any `error` text. Field names are confirmed or corrected from this.
- Check whether Contracts Finder's `keyword` filter actually narrows results (compare item counts across keywords).
- Manually review every Priority A/B row, record verdicts, and add fully reviewed items to `poc/benchmark/heldout/` (label before looking at the classifier output). That gives the first real false-positive rate.
