# Data sources — access, legality, coverage, cost

> **Business rules updated 2026-11-05:** markets are now UK, UAE and all of Europe, and there is **no budget minimum or maximum**. Statements below about the £1–3k range or UK/UAE-only scope are historical. Current rules: [live-validation.md](live-validation.md).

Phase 1 research, 2026-11-05. **Read the evidence column before relying on any row.**

## How each claim was established

| Marker | Meaning |
|---|---|
| **[live-blocked]** | We tried to reach the host from this cloud session. The environment's network policy refused it (HTTP 403 at the egress proxy, or DNS refused for server-side fetch). This tells us nothing about the source itself. |
| **[search 2026-11-05]** | Confirmed from web-search results gathered today. The source pages themselves were not opened. |
| **[prior knowledge — re-verify]** | From the author's background knowledge of the platform's published terms or docs. Treat it as a lead to check, not a fact. |

No source was retrieved directly in Phase 1. Every host we tried was denied by the session's network policy (see [feasibility.md](feasibility.md#what-was-actually-tested)).

---

## Summary matrix

| Source | Legal and technical access | Official API / authorised provider | UK/UAE SME coverage | Cost | Evidence URL | Freshness | Verdict |
|---|---|---|---|---|---|---|---|
| **UK Contracts Finder** | ✅ Open Government Licence v3; documented public API, no key **[search]** | `GET /Published/Notices/OCDS/Search` **[search]** | Public sector only. Few £1–3k contracts (see note T1) | Free | ✅ `/Notice/<guid>` | Daily | **GO** for larger work and sub-contracting. **Poor** for £1–3k |
| **UK Find a Tender** | ✅ OGL; documented API **[search]** | `GET /api/1.0/ocdsReleasePackages` **[search]** | Above-threshold public sector (typically £100k+) | Free | ✅ `/Notice/NNNNNN-YYYY` | Daily | **GO** only as a partner/sub-contract feed |
| **n8n Community (Discourse) – Jobs** | ⚠️ Public JSON is technically available. Commercial collection needs a ToS check and ideally owner permission | No official partner API. Discourse JSON is a technical endpoint | Global, mostly tool-savvy buyers and agencies. Few UK/UAE SMEs | Free | ✅ | Hours–days | **CONDITIONAL**: ask permission. Already the best-observed source of explicit buyer posts **[search]** |
| **Make Community – Hire a Pro** | ⚠️ Same as n8n. The category is the "only approved place … to post job offers" **[search]** | As above | As above | Free | ✅ | Hours–days | **CONDITIONAL** |
| **Upwork** | ✅ via official GraphQL API with OAuth2. The "Read marketplace Job Postings" scope needs an approved API key **[search]**. RSS feeds were discontinued **[prior knowledge — re-verify]** | ✅ Official API (approval required) | High volume of explicit, budgeted automation jobs. Client country is visible | API free. Platform fees on work won | ✅ | Minutes | **GO as an on-platform channel only**: you must bid and transact on Upwork. Taking clients off-platform breaches its ToS **[prior knowledge — re-verify]** |
| **Freelancer.com** | ✅ Official API, OAuth2, project search, sandbox available **[search]** | ✅ | Global, lower budgets, many low-quality posts | API free. Fees on work won | ✅ | Minutes | **GO as an on-platform channel only** |
| **PeoplePerHour** (UK-centric) | ❓ No public API found. Scraping not permitted without consent **[prior knowledge — re-verify]** | ❌ none found | Good UK SME coverage | — | ✅ | Hours | **NO automated collection.** Manual use or ask for partnership |
| **Reddit** | ❌ for commercial use without written approval. The Data API free tier is non-commercial only. Commercial use needs a contract/approval **[search]**. reddit.com also blocks this environment's search crawler | Official Data API (OAuth). Commercial pricing is negotiated and unpublished **[search]** | Strong for explicit requests (r/smallbusiness, r/automation, r/n8n, r/zapier, r/dubai, r/UKBusiness). US-skewed | Unknown (negotiated) | ✅ permalinks | Minutes | **BLOCKED pending commercial approval.** Do not scrape. Do not use unlicensed resellers |
| **LinkedIn** | ❌ No API for searching other members' posts. The User Agreement prohibits scraping and automated access **[prior knowledge — re-verify]** | Marketing / Community Management APIs cover only your own organisation's pages and need partner approval | Best UK/UAE B2B coverage of any source | Sales Navigator seat (check current price) | ✅ | Minutes | **NO automated collection.** Human-in-the-loop only: a person finds posts and logs the URL and excerpt in the CRM |
| **Facebook Groups** | ❌ Groups API deprecated (Graph API v19, 2024) **[prior knowledge — re-verify]** | None | Strong for local UK/UAE SME groups | — | ⚠️ often members-only | — | **NO.** Manual participation only, within group rules |
| **TheirStack** | ✅ Paid job-postings data provider (authorised aggregator) | ✅ API. Free tier: 200 API credits/month, 1 credit per job, max 5 pages × 25 results at 2 req/s. API plan from $59/month for 1,500 credits **[search — pricing pages; confirm in billing]** | Good UK/UAE job coverage | $0–59+/month | ✅ (job URL) | Days | **GO for enrichment only.** Job ads are *internal recruitment*, which our scoring rejects as a buying signal (see below) |
| **UAE tenders** (Dubai eSupply, Abu Dhabi procurement portal, federal MoF platform) | ❌ No public tender-data API found. Portals require supplier registration with a UAE trade licence **[search]** | None found | UAE government only | Registration costs | Behind login | Daily | **NO automated collection.** Manual, after registration |
| **Hacker News** (Algolia API) | ✅ Public API **[prior knowledge — re-verify]** **[live-blocked]** | ✅ hn.algolia.com | Very low for UK/UAE SMEs (US tech audience) | Free | ✅ | Minutes | Low priority |
| **Stack Exchange** | ✅ Public API, CC BY-SA content **[prior knowledge — re-verify]** **[live-blocked]** | ✅ | Mostly DIY technical questions (Tier D) | Free (keyed quota) | ✅ | Minutes | Low priority |
| **Buyer-request marketplaces** (Bark.com UK, Sortlist, Clutch) | ✅ when used as intended: you pay or register to respond to genuine buyer requests | Their own platforms, no data API | Bark is UK-centric | Per-lead credits (check current pricing) | On platform | Hours | **Worth a manual trial.** Not for automated collection |
| **Companies House API** | ✅ Free, official | ✅ | All UK companies | Free | ✅ | — | **GO for enrichment** (not a lead source) |
| **General web search** | ✅ Discovery only. Results are mostly vendors marketing to buyers, not buyers asking **[search]** | Search-API availability changes often. Re-verify before Phase 2 | — | Varies | ✅ | Unreliable dates | Discovery aid only |

---

## Notes that change the business case

**T1 — UK tenders rarely reach £1–3k.** Under the Procurement Act 2023 regime, below-threshold opportunities have to be published only above roughly £12k (central government) or £30k (sub-central) **[prior knowledge — re-verify]**. Contracts worth £1–3k are normally bought by quote or card without a notice. Every real automation tender we found was far larger. One example, according to the search summary (unverified): an Oldham Council intelligent-automation partner tender at £215,000 that closed on 4 Sep 2026. **Tenders are a different product line from Solvant's £1–3k packages.**

**T2 — The cleanest Tier-A demand sits inside freelance marketplaces.** Upwork and Freelancer posts are explicit, scoped, budgeted and fresh: exactly Tier A. But their terms make them **marketplace channels, not exportable leads**. The engine can surface them so the team bids quickly. It must not move those buyers into an off-platform CRM pipeline.

**T3 — Job ads are not buying signals.** TheirStack, Adzuna and Indeed show companies hiring staff. A post like "Automation Specialist, full-time" usually means the company plans to build in-house, i.e. a competitor to Solvant for that budget. A post like "Ops administrator – invoicing, data entry" shows manual-process pain: Tier C at most. Use these for account-level enrichment ("this company has manual finance ops"), never as the reason for outreach.

**T4 — Community job boards are dominated by vendors.** In the 36 real results we reviewed, 16 were vendors, recruitment or unrelated, and only about 14 were plausible buyer requests (see [intent-scoring.md](intent-scoring.md)). The UK/UAE share was small. The only UAE-linked item turned out to be an employment role.

**T5 — Data protection.** Forum handles and post text are personal data under UK GDPR and the UAE PDPL. A legitimate-interests assessment (LIA) is needed before storing them. Store the minimum (URL, excerpt, handle). Delete when the source is deleted. Honour objections. See [architecture.md](architecture.md#privacy-and-data-minimisation).

## Added 2026-11-05: EU TED

**EU Tenders Electronic Daily (TED Search API v3):** `POST https://api.ted.europa.eu/v3/notices/search`. Anonymous access for published notices. Commercial reuse is allowed with credit ([legal notice](https://ted.europa.eu/en/legal-notice), [API docs](https://docs.ted.europa.eu/api/latest/search.html)). Covers EU/EEA public procurement. **Enabled** as a permitted collector. Field names are confirmed on the first live run.

Current permission status for every collector: [live-validation.md](live-validation.md#source-permissions-automated-collection).

## Recommended source portfolio for Phase 2

1. **Contracts Finder + Find a Tender**: automated, legal, free. For bid/no-bid and sub-contracting, not the core £1–3k funnel.
2. **Upwork API** (apply for a key) and **Freelancer API**: automated alerting for on-platform bidding.
3. **n8n and Make community boards**: automated *only after* written permission from the community owners. Until then, manual review.
4. **Reddit**: apply for commercial Data API access. Decide based on Reddit's quote.
5. **LinkedIn, Facebook groups, UK Business Forums, PeoplePerHour, Bark**: a human-in-the-loop capture form in the app. A person pastes the URL and excerpt, and the engine classifies, deduplicates and scores it.
6. **TheirStack + Companies House**: enrichment and account scoring only.
