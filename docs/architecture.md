# Target architecture (Phase 2+)

Status: **proposal**. Nothing in this document is built or deployed. No database changes were made in Phase 1.

## Overview

```
                 ┌──────────────── Scheduled collectors (Supabase Edge Functions / cron) ───────────────┐
 Approved APIs → │ contracts_finder · find_a_tender · upwork* · freelancer* · discourse** · reddit***     │
                 └───────────────┬─────────────────────────────────────────────────────────────────────┘
 Manual capture (LinkedIn,       │ raw_items (URL, excerpt, timestamps, provenance)
 FB groups, forums, Bark) ──────►│
                                 ▼
                       normalise → redact PII → dedupe (canonical URL, source id, hash, shingles)
                                 ▼
                       rules classifier (guard-rail)  ──►  LLM classifier (structured output,
                                 │                         verbatim evidence spans required)
                                 ▼
                       signals (tier, score, evidence, service, fit flags)
                                 ▼
                       enrichment (Companies House, TheirStack account data, website)
                                 ▼
                 Next.js app: review queue → verify → CRM pipeline (contacted / replied / won / lost)
                                 ▼
                       monitoring: run log, source health, precision on verified outcomes

  *   on-platform alerting only: bid inside the marketplace, never export the buyer
  **  only after written permission from the community owner
  *** only after Reddit commercial Data API approval
```

## Components

| Layer | Choice | Notes |
|---|---|---|
| Web app | **Next.js** (App Router, server components) on Vercel or similar | Server-only data access. No service-role key in the browser |
| Auth | Supabase Auth (email magic link or SSO). Internal users only | Roles: `admin`, `reviewer` |
| DB | **Supabase Postgres** | Schema below. **RLS on every table** |
| Collectors | Supabase Edge Functions on `pg_cron` schedules, or a small container job | One function per source. Port of `poc/signal_engine/collectors` |
| Classification | Rules (port of `classify.py`) + Claude API with structured outputs | Batch API for non-urgent backfills |
| Enrichment | Companies House API (free), TheirStack (company endpoint), website metadata | Run only for Tier A/B, to save cost |
| CRM | Built-in lightweight pipeline first. Optional HubSpot/Pipedrive sync later | |
| Monitoring | `collection_runs` table + alert on failure or zero-yield. Sentry free tier for app errors | |

## Data model (draft)

```sql
sources(id, key, kind, terms_url, permission_status, rate_limit_per_min, enabled)
collection_runs(id, source_id, started_at, finished_at, status, fetched, new, error)
raw_items(id, source_id, source_item_id, url, canonical_url, title, excerpt,
          posted_at, collected_at, deadline_at, author_handle, organisation,
          content_hash, verification_status, deleted_at,
          unique(source_id, source_item_id), unique(canonical_url))
signals(id, raw_item_id, intent_tier, actionable, score, freshness, evidence jsonb,
        reasons jsonb, suggested_service, fit_flags text[], classifier_version, llm_model)
companies(id, name, country, companies_house_no, domain, enrichment jsonb, enriched_at)
signal_company(signal_id, company_id, match_confidence)
reviews(id, signal_id, reviewer_id, verdict, corrected_tier, note, reviewed_at)   -- benchmark source
pipeline(id, signal_id, owner_id, stage, next_action_at, notes)                   -- CRM
suppression(id, kind ['handle','domain','url'], value, reason, created_at)        -- objections / opt-outs
```

## Security

- **RLS:** enable it on every table. Only authenticated internal users can read signals. `reviewer` can insert or update `reviews` and `pipeline`. Only `admin` can change `sources`. Collectors write through `security definer` functions or the service role inside Edge Functions, never from the client.
- **Keys:** the service-role key, Claude API key and source tokens live only in Edge Function secrets or server env vars. They are never put in `NEXT_PUBLIC_*`, never committed (`.gitignore` covers `.env*`), and rotated quarterly. The repo ships `.env.example` with placeholders only.
- **Untrusted content:** all collected text is data. The LLM prompt wraps it in delimiters, instructs the model to ignore instructions inside it, uses a structured-output schema, and has no tools. Output evidence must string-match the source.
- **Least privilege per source:** read-only OAuth scopes (for example Upwork's job-postings read scope only).

## Privacy and data minimisation

- **Lawful basis:** legitimate interests for B2B prospecting, documented in an LIA *before* Phase 2 collection starts. The UAE PDPL needs a parallel review.
- **Minimise:** store the URL, a redacted excerpt of 600 characters or fewer, timestamps and a public handle. Emails and phone numbers are stripped at ingestion (already implemented and tested). Store no profile photos and no scraped personal profiles.
- **Retention:** non-actionable signals are deleted after 90 days. Rejected items keep only the hash and URL (for dedupe) for 90 days. Pipeline records are kept while the opportunity is active plus 12 months.
- **Source deletion handling:** a weekly re-check of stored URLs for A/B/C signals. If the source returns 404/410, or shows the post as deleted or closed, set `deleted_at` and purge the excerpt and handle within 72 hours. Reddit's API terms explicitly require honouring deletions.
- **Objections:** a `suppression` list is checked at ingestion. Outreach templates explain where we saw the post.
- **Transparency:** outreach always cites the public post that prompted it. No covert tracking.

## Rate limits and politeness

- Per-source limits are held in the `sources` table. The PoC client enforces a minimum interval per host, honours robots.txt for non-API pages, sends an identifying User-Agent and does not retry 4xx responses.
- Contracts Finder: no published numeric limit, and a 403 "rate limit" page has been observed **[search]**. Start at 1 request every 2 seconds, with a daily incremental window.
- TheirStack free tier: 2 requests per second, 5 pages **[search]**. Upwork and Freelancer: follow the limits in their docs and back off on 429.

## Monthly operating cost (estimate)

Volume assumption: about 3,000 items/month classified by the LLM (after rules pre-filter rejects), averaging about 1,500 input and 300 output tokens each.

| Item | Low | Expected | Notes |
|---|---|---|---|
| Supabase | $0 (Free) | $25 (Pro) | Free-tier projects pause when inactive. Pro is recommended once in use |
| Next.js hosting | $0 | $20 | Vercel Pro per seat for commercial use. Alternatives are cheaper |
| LLM classification — Claude Opus 5.5 ($4 / $20 per MTok) | $18 (Batch API, 50% off) | ~$36 + thinking overhead ≈ $45 | Default recommended model |
| LLM alternative — Claude Haiku 5.5 ($0.10 / $0.50 per MTok) | ~$1 | ~$1 | Much cheaper. Choose only if the benchmark shows equal precision |
| TheirStack | $0 (free credits) | $59 | Enrichment only |
| Upwork / Freelancer / Contracts Finder / Find a Tender / Companies House APIs | $0 | $0 | Marketplace fees apply only to work won |
| Reddit commercial API | — | **unknown** | Negotiated with Reddit. Excluded from the total |
| Sales Navigator (manual LinkedIn capture) | — | optional | Check current pricing |
| Monitoring (Sentry free) | $0 | $0 | |
| **Total (excluding Reddit and Sales Navigator)** | **≈ $20–25** | **≈ $150** | About £15–£120/month |

LLM prices are taken from Anthropic's published model table (cached 2026-10-06). Re-check them before launch.

## Explicitly out of scope until feasibility is proven

A polished dashboard, automated outreach or email sending, any LinkedIn or Facebook automation, and any scraping that the source's terms do not permit.
