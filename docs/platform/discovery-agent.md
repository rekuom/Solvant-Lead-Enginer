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

1. `cd` into the repository and run `git pull --ff-only`.
2. **Main feed, fresh hiring posts.** From `poc/`, run `python -m signal_engine.discovery.platform.forum_reader latest --days 2`. It reads the public hiring categories of the Make and n8n communities, one request per forum, and already drops "for hire", full-time salaried, commission-only, internship and volunteer posts. Then run `python -m signal_engine.discovery.platform.forum_reader thread <urls…>` for the remaining topics, at most 25.
3. **Breadth.** Run the searches below with the `WebSearch` tool (`mode: standard`). Use `allowed_domains` to focus a query on one platform group. Vary the phrasing day to day, prefer recent results, and skip URLs you've already reported. **Reddit and Threads block Anthropic's search crawler.** Don't include them in `allowed_domains` and don't work around the block.
4. For each promising search result:
   - forum, community or GitHub thread: read it with `WebFetch`;
   - social or marketplace page: use only the search-result text;
   - discard anything matching the exclusions.
5. Qualify every remaining candidate, from the forum feed and from search:
   - **intent**: `explicit_hire_request` | `recommendation_request` | `quote_request` | `partner_search` | `problem_only` | `seller_offer` | `job_seeker` | `none_or_discussion`
   - **relevance**: `relevant` | `uncertain` | `not_relevant`. Relevant means AI, automation, integrations, chatbots, CRM, data extraction, MVP or custom software.
   - **business.type**: `independent_sme` | `startup` | `solo_founder` | `small_agency` | `mid_market` | `enterprise` | `public_sector` | `unknown`
   - **score** from 0 to 100: urgency, budget stated, clarity of scope, small-business fit, recency.
   - **reason**: one sentence based on the post itself.

   Never invent budgets, company names, size or contact details. Use `unknown` when the post doesn't say.
6. Write `poc/out/agent/candidates-YYYYMMDD.json`. The folder is git-ignored; **never commit it**. The file is a JSON list of objects like this:
   ```json
   {"url": "https://…", "title": "…", "evidence_quote": "exact words showing the need (≤ 600 chars)",
    "published_at": "2026-11-18" , "page_read": true, "query": "the search used",
    "business": {"name": null, "type": "independent_sme", "size": "4 staff", "country": "UK", "industry": "accounting"},
    "budget": null,
    "qualification": {"intent": "explicit_hire_request", "relevance": "relevant", "score": 82,
                      "reason": "…", "decision_maker": "founder", "service": "n8n workflow automation"}}
   ```
7. From `poc/`, run `SUPABASE_URL=https://dfnaevcsergsphiiodtm.supabase.co SUPABASE_PUBLISHABLE_KEY=sb_publishable_y4MeQOuV_ZyEppl39oRVVw_wK_fW8Pf python -m signal_engine.discovery.platform.agent_ingest out/agent/candidates-YYYYMMDD.json --dry-run`. Check the counts, then run it again without `--dry-run`. The ingest token is injected by the session's network proxy (header `x-signal-token`). Never print or store it.
8. Report counts only: candidates, accepted, priority A/B, rejected and why. Don't put lead details in GitHub issues, commits or logs.

## Search set (rotate; about 30 per run)

**Communities** (`allowed_domains`: community.make.com, community.n8n.io, community.zapier.com):
- "looking for" developer
- "hiring" automation
- "need help" paid
- freelancer wanted

**Small-business communities** (`allowed_domains`: indiehackers.com, ukbusinessforums.co.uk, community.shopify.com, community.hubspot.com):
- looking for developer MVP
- recommend automation
- need someone to integrate

**Social, via search** (`allowed_domains`: linkedin.com, facebook.com, instagram.com, x.com; Reddit and Threads block Anthropic's crawler):
- "can anyone recommend" AI developer
- "looking for someone to automate"
- "need an n8n" OR "Make.com expert" OR "Zapier expert"
- "build an AI chatbot for my business"
- "need someone to build an MVP"
- "spending hours" manual data entry help
- "recommend a developer" small business

**Marketplaces** (`allowed_domains`: upwork.com, peopleperhour.com, freelancer.com):
- AI automation project
- n8n
- chatbot integration
- Zapier Xero

**GitHub** (`allowed_domains`: github.com):
- "looking for a contractor" OR "paid help" automation
- "will pay" integration

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
