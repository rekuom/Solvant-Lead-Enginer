# Commercial recommendation, cost and feasibility, roadmap

## What the evidence says (2026-11-06)
- **Free, permitted, automatable sources don't produce direct SME buyers in volume.**
  - GitHub: 0 of 133 real records.
  - Public tenders: relevant but formal and large; a separate channel.
- **The sources with real buyer intent are gated:**
  - freelance marketplaces (in-platform, intake only or approved APIs);
  - hire boards in tool communities (permission needed);
  - HN "Seeking freelancer" (terms to review);
  - LinkedIn, Facebook and forums (manual only);
  - lead marketplaces (paid).
- **The engine is ready for them.** The registry, intake, assessment, pipelines, privacy and blind review are built and tested. What's missing is legitimate access to the right sources.

## Recommended next steps (in priority order)
1. **Marketplace alerts → intake (cost: £0, effort: about 30 min of setup).**
   - Create saved searches and alerts on Upwork, PeoplePerHour, Malt and Freelancer.com for n8n / Make / Zapier / Power Automate / CRM / AI agent / automation.
   - Send the alert e-mails to a private mailbox and import them weekly with `intake email`.
   - This is Pipeline B. Proposals happen in-platform.
2. **Ask n8n and Make for permission** to read their Jobs and Hire-a-Pro categories programmatically. Template: read-only, low rate, attributed, no automated replies. If granted, flip the registry status; the collector already exists.
3. **Review the HN/YC terms.** If acceptable, run `multi-source-discovery` with `allow_restricted=hn_algolia` and source `hn_algolia`.
4. **Manual capture habit:** 30 min a day on LinkedIn / UK Business Forums / Facebook groups you belong to, using `intake add`. This is the best Pipeline A source for UK and UAE founder-led SMEs.
5. **Independent review.** Once at least 20 real Pipeline A/B/C items exist:
   - generate the blind `review-packet`;
   - have a person label it;
   - run `score-review`;
   - use the result as the go/no-go for the dashboard build.
6. **Optional paid tests, each needing approval:**
   - Brave Search (~$0.51 per full query-library run, estimate) for broad discovery into H;
   - a single Bark credit pack in one category to measure lead quality and cost per conversation (Pipeline G).
7. **Private storage before scale.** The repository is public. Before storing real personal lead data persistently, either make the repository private (owner decision) or move intake storage to the private Supabase project once the schema is approved.

## Cost and feasibility
| Channel | Monthly cost | Effort | Expected quality | Status |
|---|---|---|---|---|
| Tenders (CF, FTS, TED) | £0 | Low | Relevant but formal | Working |
| GitHub | £0 | Low | Very low SME yield | Working |
| Marketplace alerts → intake | £0 (platform fees on wins) | 30 min/week | High intent, competitive | Ready (needs owner alerts) |
| HN Seeking Freelancer | £0 | Low | High intent, global | Built; terms review |
| n8n / Make boards | £0 | Low | High intent | Built; permission |
| Manual social capture | £0 | 30 min/day | Highest for UK/UAE SMEs | Ready |
| Brave Search | ~$5/month credit, then metered | Low | Snippets only | Adapter ready; needs key |
| Bark / Sortlist | Credits / subscription | Low | Paid, shared leads | Not purchased |
| LLM screening | ~$0.03–$1.08/run (estimate) | — | Better nuance | Not enabled |

## Rollout
- **Stage 6a (after approval):** apply the Supabase schema to `dfnaevcsergsphiiodtm` only, through a migration, with RLS. Import the private intake store.
- **Stage 6b:** minimal review UI (review queue plus lead detail), not a polished dashboard.
- **Stage 6c:** scheduled collection, only for permitted sources, with per-run caps and alerts on failed connectors.
- **Stage 6d:** outcome tracking (conversations, proposals, wins), then source ranking by revenue per source.

## Blockers
| Blocker | Owner action |
|---|---|
| Marketplace APIs (Upwork, Freelancer) need approved credentials | Apply, or use alerts → intake |
| n8n / Make community permission | E-mail the community teams |
| HN commercial-reuse terms unconfirmed | Review the terms; opt in per run |
| No free open-web search API | Approve a small Brave budget, or skip |
| Public repository vs. personal lead data | Make the repository private, or wait for private Supabase storage |
| Independent human review | Assign a reviewer once ≥20 real items exist |
| GitHub Discussions untested | Run `multi-source-discovery` (job token enables GraphQL) |
