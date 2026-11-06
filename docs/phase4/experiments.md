# Phase 4 validation experiments: actual results

Only results that were actually executed are reported as results. Everything else is marked *not run* with the reason.

| Experiment | Executed? | Where |
|---|---|---|
| A. GitHub | **Yes, real data** (2026-11-06, 07:4x–07:59 UTC) | Claude Cloud (api.github.com reachable); evidence in [`evidence/`](evidence/) |
| B. Open-web search | **Adapter built and tested with fixtures; no live run** | No free credential-free provider exists (see below) |
| C. Marketplace ingestion | **Import pipeline built and tested** (CSV, JSON, alert e-mail, manual); **no real marketplace data** | The owner must supply alerts/exports they are entitled to |
| D. Social / community intake | **Mechanism built and tested; no real captures** | Social platforms can't be collected automatically; a person must capture posts |
| E. Agency partnerships | **Yes, within A** (GitHub partner and white-label queries) | 0 found |
| F. Procurement | **Unchanged and still validated** (held-out evaluation, Phase 3) | Pipeline E; existing `live-lead-validation.yml` |

## Experiment A: GitHub (real)

**Method:**
- 40 planned queries: 30 exact buying-intent phrases from the query library (English; GitHub is overwhelmingly English) and 10 broad keyword queries meant to stress-test noise filtering.
- `is:issue`, created in the last 60 days.
- Documented REST search API, unauthenticated (10 requests/min), 6.5 s minimum interval.
- **40 requests in total**, across two runs. Repeat prevention stopped the second run from re-requesting the first run's 25 queries.

| Measure | Result |
|---|---|
| 1. Records discovered | **134** (exact-phrase queries: 7 records from 25 queries; broad queries: 127) |
| Duplicates | 1 (133 unique) |
| 2. Records verified (content fetched from the API) | 133 |
| Technically relevant deliverable (model) | 71 relevant · 56 not relevant · 6 uncertain |
| 3–4. Relevant opportunities with explicit external-provider demand | **0** |
| 5. Independent SMEs identified | **0** |
| 6. Opportunities with an appropriate contact route | **0** |
| Pipelines | A 0 · B 0 · C 0 · D 0 · E 0 · F 0 · H (research) 11 · **Excluded 122** |
| Exclusion reasons | internal task, no invitation 47 · lead/aggregator/digest bots 33 · SEO/content marketing 12 · not software 15 · closed 9 · spam campaign 6 · lead-marketplace ad 1 · crypto bounty 1 · job seeker 1 |
| 7. False positives | Before the general detector fixes: 1 Pipeline A item (an internal "Earn & Work" release task), 2 recruitment-bot items in F, and digests in H. After the fixes: none in A–G. **This is an author review, not independent.** |
| 9. Unverified or uncertain | 11 in research (internal roadmaps and tasks that mention payments or contractors) |
| 10. Cost / runtime | $0; about 1 min per 25 requests (rate-limited) |
| 11. Restrictions | GitHub Acceptable Use Policies forbid using API data for spam or selling personal information. No comments were posted, no emails collected, and author handles are hashed. Discussions need GraphQL, which this cloud session blocks; it's enabled in the Actions workflow with the job token but **untested** |

**What GitHub actually contains** (calibration with 12 manual probes plus this run):
- the same "Looking for a Developer / IT Partner" post spammed across many repositories;
- SEO articles posted as issues;
- AI "lead watch" bots re-posting other platforms' posts as daily "Leads — date" issues;
- crypto bounty farms;
- internal roadmaps that mention "paid", "contractor" or "RFP".

Genuine "we will pay someone to build X" requests are very rare. One paid open-source contributor offer was seen during calibration.

**Verdict:** GitHub is free and permitted, but it's a **weak source of SME buyers**. Keep it as a cheap monitor for paid OSS work and partner requests. Don't expect direct-sales volume from it.

## Experiment B: open-web search (not run live)

**Findings (2026-11-06):**
- Google Custom Search JSON API: closed to new customers since 20 Jan 2026, shutting down 1 Jan 2027.
- Bing Web Search API: retired in Aug 2025.
- Brave Search API: card required and metered. Reports suggest about $5/month of credit (roughly 1,000 queries), then about $4–5 per 1,000; sources conflict.

**Built:**
- the provider interface;
- the Brave adapter, disabled without `BRAVE_SEARCH_API_KEY`;
- a fixture provider;
- a multilingual query planner: 102 buyer-intent phrases in 14 languages, plus 10 GitHub-only broad queries;
- per-query cost estimates, repeat prevention and request caps.

**Rule:** every search hit is `search_snippet_only` and goes to research (H) until verified.

**To run:** approve a Brave budget and add the key as a repository secret. A full 102-query run would cost about **$0.51** (estimate).

## Experiment C: marketplace ingestion (mechanism only)

**Supported routes:**
- manual entry;
- CSV and JSON import of alerts or exports you're entitled to;
- user-authorised alert e-mails, with Upwork, Freelancer, PeoplePerHour, Malt, Fiverr-brief and Bark link patterns;
- licensed lead files (`licensed_import`).

**Each record carries:**
- a verification state (`user_submitted` until a reviewer opens the original);
- the platform rules from the registry: proposals in-platform, off-platform contact never assumed, agency accounts allowed or not.

**Tested** with unit tests only. **No real marketplace data exists yet**, because Upwork and Freelancer API access needs approval and credentials, and Fiverr Briefs are private to matched sellers.

## Experiment D: social and community intake (mechanism only)

`intake add --source-key linkedin --url … --post-date … --text … --stated-role founder` runs the full assessment: problem, external help, employment vs. project, SME signals, missing facts and next action.

Manual entries remain **unverified** until a reviewer confirms them. Nothing was captured, because capturing LinkedIn, Facebook-group and forum posts needs a person; automated collection there isn't permitted.

## Experiment F: procurement

Unchanged from Phase 3 and kept separate (Pipeline E):
- held-out real-record gate: 14 of 15 surfaced records relevant;
- false-positive rate 3%;
- **not independently validated.**

Procurement volume isn't evidence of direct-sales success.

## Independent quality review: status

**Not achieved in this phase.** No automated, permitted source produced enough direct-sales opportunities (Pipeline A: 0) to build a top-20 review set.

The tooling is ready:
- `review-packet` produces a blind CSV with source evidence only and no model judgement;
- `score-review` computes Precision@10/@20, relevance, buying-intent, SME, engagement and contact-route agreement;
- it refuses to call the 90% gate passed with fewer than 20 reviewed items.

The first meaningful review needs the owner to feed real opportunities through intake (marketplace alerts and manual captures), or to approve the HN or forum sources.
