# Phase 4 architecture: multi-source discovery, pipelines and qualification

Code: [`poc/signal_engine/discovery/`](../../poc/signal_engine/discovery/). It reuses the Phase 1–3 classifier (`relevance.py`, `classify.py`, `markets.py`, `qualify.py`) instead of duplicating it.

```
 sources (registry-gated)                 intake (user-initiated)
 ├─ github  (REST search, GraphQL disc.)  ├─ manual CLI entry
 ├─ hn      (restricted: opt-in)          ├─ CSV / JSON (alerts, exports you're entitled to)
 ├─ feeds   (per-feed terms)              ├─ alert e-mails (.eml)
 ├─ search  (Brave adapter: disabled)     └─ licensed lead files
 └─ tenders (existing OCDS/TED collectors → Pipeline E)
          │                                   │
          ▼                                   ▼
   RawRecord (evidence only, provenance, verification state, hashed author, PII-redacted excerpt)
          │  dedupe (URL → content) · spam-campaign detection (same title, ≥3 owners)
          ▼
   assess(): independent dimensions A–J + noise flags + missing facts
          ▼
   route(): pipeline A–H / GLOBAL_REVIEW / EXCLUDED (+ reason)  →  rank() per pipeline profile
          ▼
   stage audit · private full file · redacted public report · blind review packet
```

## Components

| Module | Role |
|---|---|
| `data/source_registry.json`, `registry.py` | Source-access policy. 41 sources with status, access method, auth, rate limit, cost, commercial reuse, contact route, marketplace rules, evidence URLs and review date. **Collectors run only when the registry permits.** Restricted sources need a per-run opt-in. |
| `models.py` | `RawRecord` (evidence) is kept separate from `Assessment` (interpretation) and `Opportunity` (routing). |
| `assess.py` | Dimensions A–J, each with its own evidence and confidence. |
| `router.py` | Pipelines, ranking profiles and next actions; spam-campaign detection. |
| `querylib.py`, `data/query_library.json` | 102 buyer-intent phrases in 14 languages across 7 intent categories, plus 10 GitHub-only broad queries. Round-robin planning, per-provider language sets, cost estimates and repeat prevention (20 h TTL). |
| `connectors/github.py` | REST issue search (10 or 30 req/min) and GraphQL Discussions (token required). Budgets, stop-on-403/429, every request logged. |
| `connectors/hn.py` | Algolia HN search plus the "Seeking freelancer" thread parser. **Restricted: off unless opted in.** |
| `connectors/search.py` | Search-provider interface, Brave adapter (key required), fixture provider, RSS/Atom reader (per-feed registry key). |
| `intake.py` | Manual, CSV, JSON, e-mail and licensed intake: validation, dedupe, platform rules, private store (`poc/out/private/`, git-ignored). |
| `privacy.py` | Salted author hashes, @handle masking, PII redaction, redacted public view. |
| `run.py` | CLI covering sources, plan, discover, intake, report, review packet and score review; stage audit and run log. |

## Opportunity pipelines

| Pipeline | Enters when | Never |
|---|---|---|
| **A Direct SME** | Verified (or user-supplied, flagged) explicit hire, quote or recommendation request; relevant deliverable; target market or unknown | tenders, marketplace posts, sellers, job seekers |
| **B Freelance project** | Project posted on a freelance marketplace (via intake), or a fiat paid bounty | off-platform contact assumed |
| **C Agency partner** | White-label, subcontract, delivery-partner or "for our clients" requests | a seller advertising itself |
| **D Operational pain** | Specific relevant problem, no request to hire | presented as a buyer |
| **E Procurement** | Relevant tender (existing collectors) | promoted into A |
| **F Recruitment signal** | Employment or staff augmentation for relevant roles | counted as consultancy demand |
| **G Licensed leads** | Lead-marketplace or licensed rows (cost tracked) | — |
| **H Research / unverified** | Snippets, uncertain or product-only items, support signals | presented as a buyer |
| **GLOBAL_REVIEW** | Strong request with explicit out-of-market location | silently dropped |
| **EXCLUDED** | Noise, seller, job seeker, closed (>90 days), unrelated, fixture | — |

## Independent dimensions

| Dim | Values (examples) | Evidence rule |
|---|---|---|
| A Technical relevance | relevant / product_only / not_relevant / uncertain | Phase 3 relevance model (multilingual, acronym traps, generic words never count) |
| B Buying intent | explicit_hire_request, quote_request, recommendation_request, partner_search, paid_bounty, problem_only, employment_or_staffing, seller_offer, job_seeker, formal_procurement, none | Developer-community posts must **solicit** outside help |
| C Engagement type | agency_or_consultancy, freelance_project, contract, staff_augmentation, permanent_employment, partnership, bounty, procurement, unknown | Phrase evidence |
| D Business type | independent_sme_self_reported, agency, enterprise, public_sector, individual_or_hobby, open_source_or_unknown, unknown | Only what the post states ("team of 12", "my clinic"). **Never inferred from a job title.** Employee range shown only as "self-reported". |
| E Decision-maker access | self_reported_decision_maker, poster_role_unknown, procurement_channel | Stated role only; poster ≠ buyer by default |
| F Freshness | fresh ≤30 d / stale ≤90 d / old / closed / date_unknown | Date evidence and source status kept separate: "open" is never treated as "available" |
| G Delivery complexity | low / medium / high + flags | Phase 2 delivery flags |
| H Evidence confidence | verified_source_content / user_supplied_unverified / unverified | From the verification state |
| I Commercial potential | budget_stated / not_stated + recurring hints, crypto flag | Stated facts only; no invented value or probability |
| J Contact permission | reply_in_thread_invited, in_platform_only, formal_procurement_only, platform_rules_apply, no_unsolicited_outreach | Registry + explicit invitation in the post |
| Location | UK / UAE / Europe / other / unknown | Place evidence only (Phase 2) |

**Ranking profiles:**
- **A:** intent, then relevance, SME, decision role, freshness, permitted route, verified; minus 10 for unknown location.
- **B:** real project, scope, budget, agency eligibility, freshness.
- **C:** outsourcing demand, relevance, recurring, route.
- **D:** specificity, relevance, SME.
- **E:** relevance, freshness, minus formal-bid burden.

Every point is explained in `rank_explanation`. There's no cross-pipeline score.

**New false-positive safeguards** (all regression-tested):
- permanent job → F, not A;
- job seeker and seller listing → excluded;
- support bug → H;
- tender → E only;
- licence purchase → H;
- hobby project flagged, business type `individual_or_hobby`;
- old or closed → excluded, and "open" is never treated as "available";
- snippet → H;
- lead-marketplace advertising, SEO, AI lead-bot or digest posts, crypto bounty farms and cross-repo spam campaigns → excluded;
- internal tasks containing "paid/hire" words → excluded.

The Phase 3 tender safeguards still hold (gutter, bridge, laundry, clinical, medical consumables).

## No silent loss: ranking and caps

1. Dedupe before ranking.
2. Assess all records.
3. Route.
4. Shortlist the top N **per pipeline**.
5. Everything else stays in `opportunities_private.jsonl`, with counts in `stage_audit.json`: stage counts, exclusion reasons, duplicates, and omitted-beyond-shortlist per pipeline.

## Privacy, legal and security design

- **The repository is public.** Public outputs (Actions summary and artifacts) list records only for the actionable pipelines (A, B, C, E, G, global). Research, D and excluded records appear only as counts.
- Author handles are always hashed. Excerpts are PII-redacted, and private files are never uploaded.
- **Private intake data lives only in git-ignored `poc/out/private/`.** Storing real personal leads persistently needs private storage, which is a blocker (see roadmap). Until then, use local or private runs and redacted outputs.
- **Never done:**
  - automated messages, comments, bids or e-mails;
  - scraping behind logins, private groups or CAPTCHAs;
  - harvesting exposed AI conversations;
  - guessing e-mail addresses.
- GitHub AUP: no spam or selling of personal information. A reply is suggested only where the post invites outside help.
- UK GDPR / PECR: B2B legitimate-interest assessment still required. No unsolicited electronic marketing to individuals; outreach goes through the platform or the stated route.
- Workflows: `workflow_dispatch` only, `contents: read`, validated inputs, checkout without persisted credentials, the read-only job token used only for GitHub search, timeouts and request caps. **A failed connector makes the run fail.**

## Cost control and LLM estimate

| Item | Today | Estimate if enabled |
|---|---|---|
| GitHub, TED, Contracts Finder, Find a Tender | $0 | $0 |
| HN (if opted in) | $0 | $0 |
| Brave Search | disabled | $0.005/query → ~$0.51 per full 102-query run (estimate, sources disagree) |
| LLM screening | **not used** | Only after the deterministic filter. Example: 100 records/run × ~1,200 input + 300 output tokens. Claude Haiku 5.5 ≈ **$0.03/run**; Sonnet 5.5 ≈ **$0.54/run**; Opus 5.5 ≈ **$1.08/run**. The Batch API halves these. Cap at 200 records/run and $2/run. Estimates from published per-token prices (cached 2026-10-06). |

`--dry-run` plans queries and costs without making requests.
