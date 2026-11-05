# Phase 2 plan

> **Business rules updated 2026-11-05:** markets are now UK, UAE and all of Europe, and there is **no budget minimum or maximum**. Statements below about the £1–3k range or UK/UAE-only scope are historical. Current rules: [live-validation.md](live-validation.md).

Precondition: the go/no-go in [feasibility.md](feasibility.md) is **Conditional GO**. Phase 2 starts with a short validation step (2a). The build (2b) proceeds only if 2a passes its exit criteria.

## 2a — Live validation (1–2 weeks, about £0 spend)

| # | Task | Owner | Exit evidence |
|---|---|---|---|
| 1 | Allow these hosts in the cloud environment's network settings, or run the PoC locally: `www.contractsfinder.service.gov.uk`, `www.find-tender.service.gov.uk`, `community.n8n.io`, `community.make.com` | Rekuo | `--live` run log shows `ok` |
| 2 | Run `python -m signal_engine.pipeline --live contracts_finder,find_a_tender --since <today-30d>` daily for 7 days | Dev | `poc/out/summary.json` per day |
| 3 | Confirm the OCDS notice-URL mapping against real responses. Fix the parser if needed | Dev | Parser tests updated with a **real** captured response (OGL allows this) |
| 4 | Email the n8n and Make community owners asking for permission to monitor job and hire categories programmatically (read-only, attributed, low rate) | Rekuo | Written reply on file |
| 5 | Apply for an Upwork API key with the job-postings read scope. Create a Freelancer.com developer app | Rekuo | Keys issued, or a refusal |
| 6 | Apply for Reddit commercial Data API access, describing the use case precisely | Rekuo | Quote or refusal |
| 7 | Human-verify every HOLD_VERIFY candidate in `poc/data/search_candidates_2026-11-05.json`: open each URL and record date, status, country and real tier | Rekuo / reviewer | `poc/benchmark/gold_labels.json` updated with verified labels |
| 8 | Draft the legitimate-interests assessment (UK GDPR) and a UAE PDPL note | Rekuo / adviser | Signed LIA |

**Exit criteria for 2b** (updated 2026-11-05). Count verified Tier A/B signals in the UK, UAE or Europe, fresh (30 days or less), of any budget, collectable within the source terms.
- **Go:** 10 or more such signals per month across permitted sources, *or* Upwork/Freelancer API access granted (an on-platform channel with proven volume).
- **No-go / pivot:** fewer than 10 per month and no marketplace API access. Then pivot to a manual-assisted tool: human capture form, classifier and CRM, with no automated collection.

## 2b — Build (about 3–4 weeks)

1. **Supabase schema and RLS:** migrations under `supabase/migrations/`, as in [architecture.md](architecture.md#data-model-draft). Apply only after you approve, through the project-specific connection, with write access granted explicitly for that step.
2. **Collectors as Edge Functions:** port `ocds.py` first, then Upwork and Freelancer, then Discourse once permission arrives. Add `collection_runs` logging and zero-yield alerts.
3. **Classifier service:** port the rules (TypeScript or a Python worker). Add the Claude classification step with structured output and the verbatim-evidence check. Version both.
4. **Manual capture form:** paste URL + excerpt (LinkedIn, Facebook, forums, Bark). It runs the same dedupe, classification and storage path.
5. **Review queue (minimal UI):** a list of A/B/C signals with evidence highlighted, verify/reject buttons and corrected tier. Reviews feed the benchmark.
6. **Lightweight CRM stages:** new → verified → contacted → replied → proposal → won/lost.
7. **Enrichment:** Companies House lookup on organisation name or domain, for Tier A/B only.
8. **Deletion and retention jobs:** a weekly URL re-check and purge, as described in the architecture doc.
9. **Benchmark v2:** at least 200 human-verified items, two annotators, and a held-out 30%. Report precision/recall per source weekly.

## 2c — Measure (ongoing)

- **Weekly:** verified A/B count by source and country, A/B precision on human verdicts, reply rate, won value.
- **Kill or keep per source after 8 weeks:** keep a source only if it has produced at least one won or qualified opportunity, or its A/B precision is 0.8 or higher at volume.

## Not in Phase 2

LinkedIn or Facebook automation of any kind. Automated cold email. A public-facing product. A polished analytics dashboard.
