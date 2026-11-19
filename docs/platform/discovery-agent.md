# Daily discovery agent (scheduled Claude task)

A scheduled Claude task runs this procedure on the owner's **Claude subscription**. It uses no paid AI API and no paid search API. It finds **small, independently owned businesses, founders and startups that are actively asking for** AI automation, integration, chatbot or MVP help. It qualifies each lead and delivers it to the Solvant dashboard through `signal_engine.discovery.platform.agent_ingest`.

## Targets and exclusions

**In scope:** owners, founders, small teams and startups with an **immediate** need, such as:
- "looking for someone to automate…"
- "can anyone recommend an AI developer"
- "need help integrating…"
- "build an AI chatbot / MVP"
- "Make.com / n8n / Zapier specialist wanted"
- drowning in manual admin, when they are asking for help

**Always excluded:**
- government tenders and public or institutional procurement;
- large enterprises' formal sourcing;
- prospect lists;
- people or agencies **offering** services ("for hire", "I will…");
- job seekers;
- permanent-employment job ads;
- generic discussions with no request;
- vendor marketing pages;
- shared AI-chat links (ChatGPT, Claude, Gemini, Poe share URLs). An indexed share link can't be told apart from an accidentally exposed private conversation, and it usually contains personal data;
- posts older than 90 days.

## Permitted methods

| Platform | How the agent may use it |
|---|---|
| LinkedIn, Facebook, Instagram, X | **Search-engine results only** (WebSearch). Never fetch these pages, log in, or use their APIs. Store the URL, the title and a short quote of the request as shown in the result. |
| freelancermap.de, Codeur, PeoplePerHour, Airtable community Jobs Board | **Public listing pages** via `boards_reader`: a few page requests per run, within robots.txt, identifying User-Agent. Each listing is re-read automatically at ingest. Proposals happen in-platform, by a human. |
| Upwork, Malt, freelance.de, GULP, twago, Workana, freelance.nl | Search results only (freelance.nl disallows generic crawlers), plus the owner's alert e-mails if the forwarder is ever set up. |
| Freelancer.com API, TheirStack | **Inactive: the owner has chosen not to create these accounts.** Do not run `freelancer_feed` or `theirstack_feed`. The code stays for possible future use. |
| Business communities: AccountingWEB, Xero Central, QuickBooks, Sage; Property118, LandlordZone, Property Tribes; Amazon/eBay/Etsy seller forums; Square, Lightspeed, Toast; recruitment and professional-services communities; European founder forums | **Search results only.** Pages are not fetched. These leads arrive as snippets (at most priority B) for a human to verify. |
| Make, n8n and Zapier communities; Power Platform, HubSpot, Shopify and Airtable communities; Indie Hackers; UK Business Forums | Search results. Then read **the single public thread** (WebFetch) to confirm the request, its date and the business type. Read at most 25 pages per run and don't follow pagination or crawl. |
| GitHub issues and discussions | Search results, then read the public issue. |

Reddit and Threads block Anthropic's search crawler, so they aren't searched. Their posts reach the dashboard only through manual intake.

Volume limits per run: about 30 searches and 25 page reads. Never bypass a login, paywall, robots rule or rate limit.

## Procedure

Set this once for the commands below: `export SUPABASE_URL=https://dfnaevcsergsphiiodtm.supabase.co SUPABASE_PUBLISHABLE_KEY=sb_publishable_y4MeQOuV_ZyEppl39oRVVw_wK_fW8Pf`. Run the commands from `poc/`.

1. Run `git pull --ff-only`.
2. **Learn from results.** Run `python -m signal_engine.discovery.platform.feedback`. It ends with **today's search plan**: how many of today's ~20 searches each strategy gets. The plan follows each strategy's measured rate of qualified leads per search, and keeps one exploratory search for every strategy. Follow it. Within a strategy:
   - repeat and vary queries with `qualified > 0`, especially where `progressed_by_human` or `won` is above zero;
   - drop queries with `total ≥ 5` and `qualified = 0`;
   - treat `corrected_by_human` as a warning that you're mis-qualifying a pattern.
3. **Public project boards (main volume).** Run `python -m signal_engine.discovery.platform.boards_reader latest --days 7 --out out/agent/boards-YYYYMMDD.json`. It reads freelancermap (end-customer projects; recruiter postings come out as `employment`), Codeur (open projects), PeoplePerHour (technology and AI lists) and the Airtable community Jobs Board. It already drops stale, closed, off-topic, seller and non-fit roles (teachers, sales, admin, SEO, design…). Read every remaining listing and add a `qualification` (intent, relevance, score, reason, service) plus `business.type` and `business.country` when stated. Lower the score of vague, very-low-budget or crowded (100+ offers) projects, and drop the clearly unsuitable. Keep `kind`, `board_listing` and `facts` unchanged. A PeoplePerHour card price is not the budget when the text says "open to proposals": set `budget` to null then.
4. **Forum feed: hiring posts from the last 7 days** (kept running, not expanded). Run `python -m signal_engine.discovery.platform.forum_reader latest --days 7`. It covers the hiring sections of Make, n8n, Bubble, WeWeb, Activepieces and Latenode, and already drops sellers, unpaid, commission-only and internship posts. Each topic has a `kind`: `project_or_partner` or `employment`. Read the remaining topics with `forum_reader thread <urls…>` (at most 25).
5. **Breadth: about 20 searches** using the `WebSearch` tool (`mode: standard`), allocated by today's search plan across the strategies in the search set below. Prefer results from the last 7 days and skip undated marketplace results. **Never search Reddit or Threads**: they block Anthropic's crawler, and the block must not be worked around.
   - **Log every search, including those that found nothing**, as `{"strategy": "<tag>", "query": "<text>", "lang": "en", "kept": <candidates kept from it>}`.
   - Tag each candidate's `query` the same way: `"<strategy>: <query text>"`.
   - This is how the feedback report learns which strategies work.
6. For each promising search result:
   - forum or GitHub thread: read it;
   - social, marketplace, project-board or business-community page: use only the result text (do not fetch it);
   - discard anything matching the exclusions.
7. Qualify each candidate. Add `"kind"` to every candidate, and keep the kinds separate:
   - `customer`: a business wants work done for itself (outside a marketplace);
   - `marketplace`: a project posted on a freelance marketplace or project board (in-platform proposal only);
   - `partner`: an agency or platform wants a delivery partner;
   - `employment`: a salaried or staff role. These are kept, but in a separate pipeline.

   Then fill in intent, relevance, business type, score and reason as defined above.
   - Prefer independently owned businesses in the **UK, Europe and the UAE**. Record the country only when the post states it.
   - Never invent details.
   - Put the stated budget in `budget` exactly as written (e.g. "€2,000", "£25/hour"). Never estimate one.
8. Write `out/agent/candidates-YYYYMMDD.json` as `{"candidates": [...], "searches": [...]}`. The folder is git-ignored; never commit it.
9. Run `python -m signal_engine.discovery.platform.agent_ingest out/agent/boards-YYYYMMDD.json out/agent/candidates-YYYYMMDD.json --dry-run`, check the counts, then run it again without `--dry-run`. The search log is saved at the same time.
   - **Automatic verification:** the ingest re-reads every forum and GitHub lead from the original publisher's official API. On success it stores the source's own title, date and text, marked "Verified (source API)". Posts that have been removed are rejected. No manual verification is needed for these.
   - Board listings are re-read from the board: closed listings are flagged and excluded, removed ones rejected.
   - **Ranking:** urgency, buying intent, suitability and realistic value.
     - Freshness: the last 7 days rank first; 8–30 days old is at most priority B; older is at most C.
     - Region: UK, Europe and UAE leads rank higher.
     - Urgency ("urgent", "ASAP", "this week", "deadline", and the DE/FR/ES/NL/IT equivalents) adds points.
     - Value: a stated budget of £1,000 or more, and more so £5,000 or more, adds points. Under £300 loses points, and under £100 loses a lot. Hourly rates are treated as a roughly 20-hour job.
     - Crowding: marketplace projects with 50 or more bids lose points.
   - **Pipelines stay separate:** customers → A (direct SME); marketplace → B; partners → C; employment → F.
   - The ingest token is injected by the session's network proxy. Never print it.
10. Report counts only: candidates; accepted; priority A, B and C; customer, marketplace, partner and employment counts; board counts per source; searches run per strategy and how many produced a kept candidate; how many were verified automatically; rejected and why; and which queries produced qualified leads.

**Measured yields (2026-11-19 experiments):**

| Strategy | Searches | Kept |
|---|---|---|
| Public project boards (reader) | 4 boards | 20 qualified projects from the last 7 days (Codeur 9, PeoplePerHour 7, freelancermap 3, Airtable 1) |
| Spanish searches (Workana) | 1 | Many open projects, mostly agencies wanting white-label partners (kind `partner`). Workana is search-only. |
| Accounting / property / Xero community searches | 3 | 0. Vendor pages and news. |
| DE / FR searches on freelance.de, GULP, Malt | 3 | 0. Freelancer profiles (sellers). |
| Social (LinkedIn, UAE) | 1 | 0. Seller profiles. |
| Shopify community job listings | 1 | Mostly agencies advertising; about one merchant request a month. |

Lesson: search engines index sellers far more than buyers. Business-community and multilingual searches work best when they target **project or request pages** (e.g. `workana.com/job`, `/projects/`, "Evaluando propuestas"), not general topics. Keep them exploratory: the plan will shift budget once the search log has data.

**Daily expectations:** quality over quota. The measured supply of explicit, fresh, public requests is a few per day. Don't fill the quota with weak signals, sellers or stale posts.

## Search set (rotate by feedback; about 20 per run)

The weight is on **ordinary businesses in plain business language**, not technical communities. Strategy tags (use exactly): `biz-ecommerce`, `biz-accounting`, `biz-property`, `biz-hospitality`, `biz-recruitment`, `biz-services`, `founder`, `social`, `board-search`, `tech-forum`, `github`, `de`, `fr`, `es`, `nl`, `it`, `uae`. The feedback plan allocates searches across them.

**Business communities, plain language** (`allowed_domains`: one group per query):
- E-commerce (community.shopify.com, sellercentral.amazon.co.uk, community.ebay.co.uk, community.etsy.com, wordpress.org): "recommend someone to connect" orders inventory; "need help automating" orders; "who can set up" stock sync
- Accounting and bookkeeping (accountingweb.co.uk, central.xero.com, quickbooks.intuit.com, community.sage.com): "can anyone recommend" automation practice; "pay someone to" integrate; "looking for a developer" Xero
- Property and lettings (property118.com, landlordzone.co.uk, propertytribes.com): "software to automate" tenant; "looking for someone to build"; "recommend a developer" letting agent
- Hospitality and retail (community.squareup.com, community.lightspeedhq.com, community.toasttab.com): "integration" bookings help wanted; "need someone to set up" automation
- Recruitment agencies (community.bullhorn.com, recruitmentjuice.com): "automate" candidate workflow recommend; "integration" ATS help
- Professional services and general small business (ukbusinessforums.co.uk, startups.co.uk, community.clio.com, community.hubspot.com, indiehackers.com): "recommend" automation consultant; "need someone to integrate"; "AI chatbot for my business"

**European markets, in the local language** (no `allowed_domains`, or the national boards and founder forums below):
- DE (freelancermap.de, freelance.de, gulp.de, gruenderszene.de): "suche Freelancer" Automatisierung; "Projekt" n8n OR Make Automatisierung; "Unterstützung gesucht" KI Chatbot; "Schnittstelle" Shopify Lexoffice OR DATEV
- FR (codeur.com, malt.fr, freelance-info.fr): "recherche freelance" automatisation; "besoin d'aide" intégration CRM; "projet" chatbot IA PME
- ES (workana.com/job, malt.es): "busco" experto automatización n8n; "agente IA" WhatsApp pyme proyecto; "necesito" integración CRM. Agency requests → kind `partner`.
- NL (planetfreelance.nl, malt.nl): "gezocht" automatisering freelancer; "hulp nodig" koppeling Exact OR Moneybird
- IT: "cerco sviluppatore" automazione; "cerco freelance" integrazione gestionale

Record the country (and language) only when the post states it. Quotes stay in the original language; write `reason` in English.

**Technical forums, help threads offering payment (low volume; keep to about 2 per run)** (`allowed_domains`: one of community.make.com, community.n8n.io, forum.bubble.io, community.openai.com):
- "willing to pay"
- "hire someone"

**Marketplaces and project boards, search result only** (`allowed_domains`: peopleperhour.com, upwork.com, malt.co.uk, freelancermap.de, codeur.com). Skip freelancer.com when its API feed is active. Keep only project or job pages, never seller listings:
- n8n project
- Make.com automation project
- AI chatbot integration project
- Zapier Xero
- (UK) peopleperhour automation

**GitHub** (`allowed_domains`: github.com):
- "looking for a contractor" automation
- "paid" "help wanted" integration
- "will pay" bot

**Social, search result only; low yield, keep to about 3 per run** (`allowed_domains`: linkedin.com, x.com, facebook.com, instagram.com):
- "looking for" n8n OR Make.com expert Dubai OR UAE
- "recommend" automation agency UK small business
- "suche" Automatisierung Freelancer
- "recherche" freelance automatisation

## Results in the dashboard

Each lead shows:
- the original URL and its source platform;
- the quoted evidence of intent;
- Claude's reason, kept as a separate "LLM" classification alongside the engine's rules;
- business details;
- the priority score and pipeline;
- the verification state:
  - **"Unverified (search result)"**: the page wasn't opened;
  - **"Unverified (page read by discovery agent)"**: the agent read the public thread;
  - **"Verified (source API)"**: re-read from the publisher's official API (forums, GitHub, Freelancer.com);
  - **"Licensed import"**: from the TheirStack job-data API (employment pipeline only).

Marketplace alert e-mails (Upwork, Freelancer, PeoplePerHour, Malt, freelancermap, Codeur) are delivered continuously by the e-mail forwarder (`integrations/email-alert-forwarder`). They appear in pipeline B without any action from the daily task.

A human opens the original and clicks **Mark as verified** before any outreach. Unverified search results are never priority A.
