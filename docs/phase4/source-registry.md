# Source registry and ranking (Phase 4)

Generated from [`poc/signal_engine/discovery/data/source_registry.json`](../../poc/signal_engine/discovery/data/source_registry.json) (review date 2026-11-06).
Statuses: **permitted** (automated collection allowed), **restricted** (built or possible, but only with explicit opt-in, approval or credentials),
**manual_only** (user-initiated capture/import only), **licensed** (paid or licensed access), **unknown** (terms not verified: not collected),
**prohibited** (unavailable or not allowed). Network reachability is never treated as permission.

Facts marked in the notes come from 2026-11-06 research (official pages where found; several third-party sources disagree on pricing — see notes).
Key changes since earlier phases: Google Custom Search JSON API closed to new customers (shuts down 1 Jan 2027); Bing Web Search API retired
(Aug 2025); Brave Search API metered with card (~$5/month credit reported); X API pay-per-use since Feb 2026; Bluesky post search needs auth.

## Ranked source families for Solvant (commercial value × legitimate access)

| Rank | Source family | Why | Access today | Next step |
|---|---|---|---|---|
| 1 | Freelance marketplaces (Upwork, PeoplePerHour, Malt, Freelancer, Fiverr Briefs) | Highest density of explicit, budgeted implementation requests | **Intake only** (alerts/e-mail/manual); Upwork & Freelancer APIs need approval/credentials | Owner sets up saved-search alerts; import via `intake email/csv`; apply for Upwork API key |
| 2 | Ecosystem communities with hire boards (n8n Jobs, Make Hire a Pro) | Explicit buyers asking for exactly Solvant's skills | Collector built; **disabled until permission** | Ask n8n/Make for written permission; manual capture meanwhile |
| 3 | Hacker News "Freelancer? Seeking freelancer?" monthly thread | Explicit SEEKING FREELANCER posts | Connector built; **restricted** (commercial reuse terms unconfirmed) | Owner reviews HN/YC terms; then run with `allow_restricted=hn_algolia` |
| 4 | LinkedIn / Facebook groups / UK Business Forums / Indie Hackers | Founder-led SME requests and recommendations | **Manual capture only** (no permitted API; scraping prohibited) | Use `intake add` for posts a person found; reviewer verifies |
| 5 | Lead marketplaces (Bark, Sortlist) | Buyers who asked to be contacted | **Licensed** (paid credits/subscription) — nothing purchased | Optional paid trial with cost tracking in Pipeline G |
| 6 | Public procurement (Contracts Finder, Find a Tender, TED) | Real, legal, free; but large/formal | **Permitted, working** (Pipeline E) | Keep; never mix into direct SME pipeline |
| 7 | Reddit / X / Bluesky | Some explicit requests | Commercial approval / paid / auth required | Revisit only with approval & budget |
| 8 | GitHub Issues/Discussions | Free and permitted, but **real run found 0 SME buyers in 133 records** (noise dominated) | **Permitted, working** | Keep as low-cost monitor for paid OSS / partner requests only |
| 9 | Stack Exchange / DEV / GitLab / support forums | How-to questions; solicitation usually prohibited | Permitted/unknown | Operational-pain research only |
| 10 | Open-web search APIs | Broad discovery, snippets only | **No free credential-free route**; Brave adapter built, disabled | Approve a small Brave budget if broad discovery is wanted |

## Lead-marketplace comparison (nothing purchased)

| Marketplace | Leads available | Automation/AI/software leads? | Countries | Pricing model | Exclusivity / competition | Refunds | Export / storage licence | Buyer requested contact? |
|---|---|---|---|---|---|---|---|---|
| Bark | Buyer requests by category | Categories exist for web/software/IT; AI-automation specific volume unknown | UK, IE, US, CA, AU, NZ, ZA, more | Credits per lead; price varies by country (~$2.35/credit on US page); credits bought after 1 Nov 2025 expire after 3 months | Shared with several professionals (exact cap not confirmed) | Bark has guarantee/refund terms (not verified in detail) | Not verified — treat as in-platform | Yes (buyer posts to receive quotes) |
| Sortlist | Agency briefs | Yes (digital/dev agencies) | EU + UK + US | Agency subscription; pricing not published | Reviewers report briefs quickly taken by other agencies | Unknown | Unknown | Yes |
| Clutch / GoodFirms / DesignRush | Directory profiles (inbound) | Yes | Global | Paid profiles/sponsorship | Many competing agencies | n/a | n/a | Inbound only |
| Fiverr Briefs | Briefs matched privately to sellers | Yes | Global | Free to respond (Fiverr fees on orders) | Matched sellers only; 72-hour window | n/a | No export (in-platform) | Yes |

## Full registry

| Source | Family | Status | Automated collection | Pipelines | Contact route | Buying-intent quality | Cost | Notes |
|---|---|---|---|---|---|---|---|---|
| UK Contracts Finder (OCDS API) | procurement | **permitted** | enabled | E | formal procurement process | medium | free | Existing collector. API ignores `keyword` (run 42174857442): one paginated pull + client-side relevance screening. |
| UK Find a Tender (OCDS API) | procurement | **permitted** | enabled | E | formal procurement process | medium | free | Existing collector. |
| EU TED Search API v3 | procurement | **permitted** | enabled | E | formal procurement process | medium | free | Existing collector; anonymous search; reuse incl. commercial with credit. |
| UAE government tender portals (Dubai eSupply, Abu Dhabi, federal MoF) | procurement | **manual_only** | no | E | supplier registration required | medium | free | No public data API found; supplier registration with UAE trade licence required. |
| GitHub Issues (REST search API) | developer_community | **permitted** | enabled | A, B, C, D, H | reply in the issue only where outside paid help is explicitly invited; never email harvesting (GitHub AUP) | low | free | Real calibration (2026-11-06, 12 queries): results dominated by SEO spam, AI lead-bot issues, crypto bounty farms and internal task trackers; genuine SME buyers rare. Noise detectors required. |
| GitHub Discussions (GraphQL search) | developer_community | **permitted** | enabled | A, C, H | reply in discussion where solicitation is welcome | unknown | free | GraphQL requires a token; blocked in Claude Cloud; runs in Actions with GITHUB_TOKEN. Untested. |
| Hacker News (official API + Algolia HN Search) | developer_community | **restricted** | built, disabled (needs opt-in/permission/credentials) | A, B, C, F | reply on HN or the contact method the poster published | high (monthly 'Freelancer? Seeking freelancer?' thread has explicit SEEKING FREELANCER posts) | free | Official read API intended for third-party apps; commercial reuse terms not found. Collector built, DISABLED until the owner reviews terms (--allow-restricted hn_algolia). |
| Stack Exchange API | developer_community | **permitted** | permitted; connector not built | D, H | answer on-site only; solicitation not allowed | low | free | Mostly how-to questions (operational pain at best). Content CC BY-SA with attribution. Connector not built (low commercial intent). |
| GitLab public issues | developer_community | **unknown** | no | H | unknown | low | free | Not researched in depth; expected similar to GitHub with less volume. |
| DEV Community (Forem API) | developer_community | **unknown** | no | D, H | comment on-site | low | free | Articles, not requests. Not built. |
| Indie Hackers | entrepreneur_community | **unknown** | no | A, D | on-site replies | medium | free | No public API found; terms not reviewed. Manual capture only. |
| Paid issue-bounty platforms (Algora, IssueHunt, Gitcoin, Opire) | bounty | **unknown** | no | B | platform claim/submit | low | free | Developer bounties for open-source fixes: real money but not SME implementation demand. Crypto bounty farms seen on GitHub are excluded as noise. |
| Upwork (GraphQL API) | freelance_marketplace | **restricted** | no | B | in-platform proposal only (uses Connects) | high | free | Official GraphQL API with marketplace job-posting search scope; requires approved API key; terms must be read. No auto-proposals. Not built: needs credentials + approval. |
| Fiverr Briefs (matched client briefs) | freelance_marketplace | **manual_only** | no | B | respond inside Fiverr within 72h | medium | free | Briefs are matched privately to sellers (dashboard + email); no public feed or API. Intake via user-authorised email alert import or manual paste. |
| Freelancer.com (official API) | freelance_marketplace | **restricted** | no | B | in-platform bid only | medium | free | Official API with OAuth2 and project search (per SDK docs); app registration required. Not built: needs credentials. |
| PeoplePerHour | freelance_marketplace | **manual_only** | no | B | in-platform proposal | medium | free | No public API found. UK-heavy buyers. Intake via alerts/manual. |
| Malt | freelance_marketplace | **manual_only** | no | B | in-platform | medium | free | European (FR/DE/ES/NL/BE/UK). No public API found. Intake via alerts/manual. |
| Contra | freelance_marketplace | **manual_only** | no | B | in-platform | low | free | Commission-free; no public API found. |
| Guru | freelance_marketplace | **unknown** | no | B | in-platform | low | free | Not researched in depth. |
| Bark.com | lead_marketplace | **licensed** | no | G | respond via Bark after paying credits | medium | credits per lead | Credits vary by country (~$2.35/credit US page); credits bought after 1 Nov 2025 expire after 3 months; leads shared with several providers. Purchase nothing; import purchased leads only. |
| Sortlist | lead_marketplace | **licensed** | no | G | respond via Sortlist | medium | subscription (unpublished) | Agency-side pricing not published; reviewers report leads are quickly reserved by competing agencies. |
| Clutch / GoodFirms / DesignRush (agency directories) | lead_marketplace | **unknown** | no | G | inbound via profile | low | free | Directories: inbound enquiries to a paid profile, not a lead feed. |
| LinkedIn | social | **manual_only** | no | A, C, D, F | platform messaging/comments per LinkedIn rules | high | free | No API to search others' posts; User Agreement prohibits scraping. Manual capture only. |
| Facebook groups | social | **manual_only** | no | A, D | inside the group, per group rules | medium | free | Groups API deprecated (2024). Never scrape private groups. Manual capture only. |
| Reddit Data API | social | **restricted** | no | A, D | on-Reddit replies per subreddit rules | high | free | Commercial use needs written approval; free tier non-commercial. Not built. |
| X API | social | **restricted** | no | A, D | on-platform | medium | pay-per-use | Pay-per-use since Feb 2026 (~$0.005/post read reported); paid. Not built. |
| Bluesky (AT Protocol) | social | **restricted** | no | A, D | on-platform replies | low | free | searchPosts requires authentication (403 anonymous, per multiple reports). Needs an app password. Not built. |
| Mastodon instances | social | **unknown** | no | D | on-platform | low | free | Per-instance policies; full-text search usually needs auth. Not built. |
| n8n Community – Jobs | ecosystem_community | **restricted** | built, disabled (needs opt-in/permission/credentials) | A, B, C | reply on the job thread | high | free | Public Discourse JSON reachable (run 42032803184); terms not reviewed; permission not obtained. Collector disabled. |
| Make Community – Hire a Pro | ecosystem_community | **restricted** | built, disabled (needs opt-in/permission/credentials) | A, B, C | reply on the Hire a Pro thread | high | free | As n8n. |
| Zapier Community | ecosystem_community | **unknown** | no | D | unknown | medium | free | Support forum; solicitation rules not verified. |
| Microsoft Power Platform Community | ecosystem_community | **unknown** | no | D | support forum; solicitation likely prohibited | low | free | Support forum. |
| CRM vendor communities (HubSpot, Salesforce Trailblazer, Pipedrive, Zoho, GoHighLevel) | ecosystem_community | **unknown** | no | D | support forums; partner directories | medium | free | Support forums usually prohibit solicitation; vendor partner programmes are the legitimate route. |
| Platform communities (Shopify, WooCommerce, Xero, QuickBooks, Airtable, Notion, Bubble, Webflow, Stripe) | ecosystem_community | **unknown** | no | D | support forums; experts directories | medium | free | Several run official 'experts/partners' directories (inbound). Not built. |
| UK Business Forums | entrepreneur_community | **manual_only** | no | A, D | on-forum, per rules | medium | free | No API; no permission. Manual capture only. |
| Permitted RSS/Atom feeds | feed | **permitted** | enabled | A, B, C, D, E | per feed | unknown | free | Generic connector; feeds must be individually registered with their terms. None registered yet. |
| Brave Search API | web_search | **licensed** | built, disabled (needs opt-in/permission/credentials) | H | n/a (discovery only) | n/a | paid / small monthly credit | Card required; reported ~$5/month free credits then metered (~$5 per 1,000; sources disagree). Brave help: 'Data for Search'/'Data for AI' plans do not permit retaining any part of the API output (storage-rights plan required); no rights to linked third-party pages. Adapter built; runs only with BRAVE_SEARCH_API_KEY + explicit enable; record-level output withheld unless retention is permitted. |
| Google Custom Search JSON API | web_search | **prohibited** | no | H | n/a | n/a | free | Closed to new customers since 20 Jan 2026; shuts down 1 Jan 2027. |
| Bing Web Search API | web_search | **prohibited** | no | H | n/a | n/a | free | Retired 11 Aug 2025 (endpoints return 410). |
| AI community project boards (e.g. Hugging Face forums, Discord servers) | ai_community | **unknown** | no | A, H | per community rules | low | free | Only intentionally public requests where the author seeks help. Never search exposed private chats/unlisted conversation links. |
| UK Companies House API | enrichment | **permitted** | permitted; connector not built | — | n/a | n/a | free | Free official API (key required) for company verification; not built yet. |
