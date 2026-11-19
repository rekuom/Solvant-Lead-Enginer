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
| Upwork, Freelancer, PeoplePerHour (job pages) | Search results only. Proposals happen in-platform, by a human. |
| Make, n8n and Zapier communities; Power Platform, HubSpot, Shopify and Airtable communities; Indie Hackers; UK Business Forums | Search results. Then read **the single public thread** (WebFetch) to confirm the request, its date and the business type. Read at most 25 pages per run and don't follow pagination or crawl. |
| GitHub issues and discussions | Search results, then read the public issue. |

Reddit and Threads block Anthropic's search crawler, so they aren't searched. Their posts reach the dashboard only through manual intake.

Volume limits per run: about 30 searches and 25 page reads. Never bypass a login, paywall, robots rule or rate limit.

## Procedure

Set this once for the commands below: `export SUPABASE_URL=https://dfnaevcsergsphiiodtm.supabase.co SUPABASE_PUBLISHABLE_KEY=sb_publishable_y4MeQOuV_ZyEppl39oRVVw_wK_fW8Pf`. Run the commands from `poc/`.

1. Run `git pull --ff-only`.
2. **Learn from results.** Run `python -m signal_engine.discovery.platform.feedback`. Then adjust today's searches:
   - repeat and vary queries and sources with `qualified > 0`, especially where `progressed_by_human` or `won` is above zero;
   - drop queries with `total ≥ 5` and `qualified = 0`;
   - treat `corrected_by_human` as a warning that you're mis-qualifying a pattern.
3. **Main feed: hiring posts from the last 7 days.** Run `python -m signal_engine.discovery.platform.forum_reader latest --days 7`. It covers the hiring sections of Make, n8n, Bubble, WeWeb, Activepieces and Latenode, and already drops sellers, unpaid, commission-only and internship posts. Each topic has a `kind`: `project_or_partner` or `employment`. Read the remaining topics with `forum_reader thread <urls…>` (at most 25).
4. **Breadth: about 20 searches** using the `WebSearch` tool (`mode: standard`), spread across the groups in the search set below. Prefer results from the last 7 days and skip undated marketplace results. **Never search Reddit or Threads**: they block Anthropic's crawler, and the block must not be worked around.
5. For each promising search result:
   - forum or GitHub thread: read it;
   - social or marketplace page: use only the result text;
   - discard anything matching the exclusions.
6. Qualify each candidate. Add `"kind"` to every candidate:
   - `customer`: a business wants work done for itself;
   - `partner`: an agency or platform wants a delivery partner;
   - `employment`: a salaried or staff role. These are kept, but in a separate pipeline.

   Then fill in intent, relevance, business type, score and reason as defined above.
   - Prefer independently owned businesses in the **UK, Europe and the UAE**. Record the country only when the post states it.
   - Never invent details.
7. Write `out/agent/candidates-YYYYMMDD.json`. The folder is git-ignored; never commit it.
8. Run `python -m signal_engine.discovery.platform.agent_ingest out/agent/candidates-YYYYMMDD.json --dry-run`, check the counts, then run it again without `--dry-run`.
   - **Automatic verification:** the ingest re-reads every forum and GitHub lead from the original publisher's official API. On success it stores the source's own title, date and text, marked "Verified (source API)". Posts that have been removed are rejected. No manual verification is needed for these.
   - **Ranking:** the last 7 days rank first; 8–30 days old is at most priority B; older is at most C. UK, Europe and UAE leads rank higher.
   - The ingest token is injected by the session's network proxy. Never print it.
9. Report counts only: candidates; accepted; priority A, B and C; customer, partner and employment counts; how many were verified automatically; rejected and why; and which queries produced qualified leads.

**Daily expectations:** quality over quota. The measured supply of explicit, fresh, public requests is a few per day. Don't fill the quota with weak signals, sellers or stale posts.

## Search set (rotate by feedback; about 20 per run)

**Help threads that offer payment, by forum** (`allowed_domains`: one forum per query, from community.make.com, community.n8n.io, forum.bubble.io, community.weweb.io, community.retool.com, community.latenode.com, community.activepieces.com, community.openai.com, forum.uipath.com):
- "willing to pay"
- "paid help"
- "hire someone"
- "looking for someone to"
- "need a freelancer"

**Small-business and founder forums** (`allowed_domains`: indiehackers.com, ukbusinessforums.co.uk, community.shopify.com, community.hubspot.com):
- looking for developer
- recommend automation
- need someone to integrate
- AI chatbot for my business

**Marketplaces, search result only** (`allowed_domains`: freelancer.com, peopleperhour.com, upwork.com). Keep only project or job pages, never seller listings:
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
  - **"Unverified (page read by discovery agent)"**: the agent read the public thread.

A human opens the original and clicks **Mark as verified** before any outreach. Unverified search results are never priority A.
