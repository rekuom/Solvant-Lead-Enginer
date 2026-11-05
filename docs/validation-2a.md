# Phase 2A — live source validation

Run date: 2026-11-05 (≈10:08–10:16 UTC) · Branch `claude/trusting-hawking-kqus6b`
Raw evidence from this run: [`docs/evidence/phase-2a/`](evidence/phase-2a/) (probe, verify and discover logs, funnel, lead review).

## Headline

**The four domains you allowed were still blocked in this session.** Every request was refused by this session's own egress gateway at the CONNECT step, so no request reached any source server. As a result:

- **0** source pages were retrieved.
- **0** of the 47 candidate links could be verified.
- **0** new items were collected.
- **0** leads are verified or qualified.

No data was invented to fill the gap. The validation tooling is built and tested, so the whole Phase 2A run takes one command once the network allows it (see [Re-run](#re-run-when-access-works)).

Most likely cause: the network allow-list change was saved after this session's container started, and the policy is applied when a session starts. **Start a new session, or run the command on a local machine.** Also check that the four domains appear under the environment's *Network access → Allowed domains*.

---

## Task 1 — Network access

Probe: `python3 -m signal_engine.validate probe` (16 endpoints across 4 domains). Full table: [`evidence/phase-2a/probe.md`](evidence/phase-2a/probe.md).

| Domain | Endpoints tested | HTTP status | Response type | Redirects | Through PoC code | Diagnosis |
|---|---|---|---|---|---|---|
| `www.contractsfinder.service.gov.uk` | robots.txt, OCDS search, OCDS search + keyword, notice page | 403 on CONNECT, from our proxy | none | none | collector → `proxy_block` | **Our network policy.** The origin was never contacted |
| `www.find-tender.service.gov.uk` | robots.txt, OCDS release packages, notice page | 403 on CONNECT, from our proxy | none | none | collector → `proxy_block` | **Our network policy** |
| `community.n8n.io` | robots.txt, `/c/jobs/13.json`, `/t/326857.json`, `search.json`, `/tos` | 403 on CONNECT, from our proxy | none | none | collector → `proxy_block` (robots unreachable) | **Our network policy** |
| `community.make.com` | robots.txt, `/c/hire-a-pro/50.json`, `/t/97223.json`, `/tos` | 403 on CONNECT, from our proxy | none | none | collector → `proxy_block` | **Our network policy** |

**How a proxy block is told apart from an upstream refusal:**

| Signal | Proxy / network-policy block (seen here) | Upstream refusal (not seen) |
|---|---|---|
| Where the 403 comes from | The local proxy's answer to `CONNECT host:443`. curl shows `CONNECT tunnel failed, response 403`. urllib raises `URLError('Tunnel connection failed: 403 Forbidden')` | An HTTP response from the origin after the TLS handshake. urllib raises `HTTPError(403)` |
| TLS handshake with the origin | Never happens | Happens |
| Proxy status endpoint | `recentRelayFailures`: `connect_rejected … gateway answered 403 to CONNECT (policy denial or upstream failure)` for all four hosts | No entry |
| Control | `api.github.com` returned 200 through the same proxy, so the proxy itself works | — |
| Server-side fetch (WebFetch) | `getaddrinfo ENOTFOUND` for `community.n8n.io` and `www.contractsfinder.service.gov.uk` (the session's DNS policy) | — |

The client now records the kind of every failure: `proxy_block`, `dns_blocked`, `auth_required`, `upstream_forbidden`, `rate_limited`, `not_found`, `upstream_error`, `timeout`, `robots_disallowed` or `bad_response`. A robots.txt that can't be reached is reported as a network failure, not as "robots disallows". Phase 1 had this wrong.

Authentication requirements and API limits on these sources **could not be observed**, because no request reached them.

## Task 2 — Collecting real source content

| Action | Result |
|---|---|
| Re-fetch the 36 Phase 1 candidates (Discourse `/t/<id>.json`; tender single-notice JSON) | **0/36 verified.** All `proxy_block` |
| Additional discovery: web search restricted to the n8n and Make communities, UK and UAE wording | **11 new candidate URLs** (titles only), saved in [`poc/data/search_candidates_2026-11-05b.json`](../poc/data/search_candidates_2026-11-05b.json) |
| Re-fetch the 11 new candidates | **0/11 verified.** All `proxy_block` |
| Collectors: Contracts Finder (last 30 days), Find a Tender, n8n Jobs, Make Hire a Pro | **0 items.** All `proxy_block` |

For every item, the per-item record holds all the requested fields: URL, publication date, buyer request, external-provider evidence, UK/UAE location evidence, scope, budget, open status, data-use permission, deliverability. Each is the literal value `unknown` unless the source showed it. With no page fetched, every date, location, budget and status is `unknown`. See [`evidence/phase-2a/lead_review.md`](evidence/phase-2a/lead_review.md); the full records are in `poc/out/validation/leads.jsonl` when you run the tool.

UK/UAE hints among the 47 candidate titles:
- [AI Automation Builder — paid per project (London / Kent, UK only)](https://community.make.com/t/ai-automation-builder-paid-per-project-london-kent-uk-only/109977). The only title naming a UK place. The classifier rates it **D**; the search summary describes an agency sourcing builders as its own clients land, about 5 months old (unverified). Not an end-buyer lead.
- [🚀 HIRING: n8n Automation Expert to Build AI Agent Workflows (Freelance)](https://community.n8n.io/t/hiring-n8n-automation-expert-to-build-ai-agent-workflows-freelance/118535?page=2). Only the search summary says it comes from a UAE startup. The low topic id suggests an old post.
- [WeActivate](https://community.make.com/t/weactivate-make-workflow-automation-ai-and-api-integrations-dubai/117966). A Dubai **vendor**, i.e. a competitor.
- [Hiring: AI Growth & Automation Specialist](https://community.n8n.io/t/hiring-ai-growth-automation-specialist-remote-potential-growth-partnership/323364?tl=en). A UAE employer, per the summary. **Recruitment**, so rejected.

## Task 3 — Strict commercial qualification

Implemented in [`poc/signal_engine/qualify.py`](../poc/signal_engine/qualify.py) and covered by 21 new tests. A lead is **QUALIFIED** only if all of these hold:
- the source content was seen (`verified_api` or `human_verified`);
- it was published 30 days ago or less;
- there is UK/UAE **place** evidence (currency symbols no longer count; the tests caught that bug);
- the intent tier is A or B;
- it is not vendor, recruitment or unrelated;
- it is not closed;
- the budget is not far above the £1–3k range;
- Solvant can deliver it.

Search titles can never qualify.

**Intent and availability are tracked separately:**
- `intent_verified` is true only when the content was seen and shows a Tier A/B request.
- `availability` is one of:
  - `verified_open`: the source shows a future deadline;
  - `no_visible_closure`: the forum topic isn't closed, but **this is not proof the opportunity is open**;
  - `closed`;
  - `unknown`.

Result on the 47 candidates: **QUALIFIED 0 · NEEDS_REVIEW 19 · EXCLUDED 28.**
- The 19 NEEDS_REVIEW items have Tier A/B titles but no verified content, date or location.
- Exclusion reasons: 7 vendor, 7 recruitment, 9 Tier D, 3 unrelated, 2 physical automation.

## Task 4 — Lead quality review

**No real lead could be manually reviewed, because no content could be retrieved.** The lead table ([`evidence/phase-2a/lead_review.md`](evidence/phase-2a/lead_review.md)) lists all 19 high-intent titles. For every one, buyer, country and date are `unknown`, confidence is `low (title only)`, and the action is "human check".

**Held-out evaluation set:** [`poc/benchmark/heldout/`](../poc/benchmark/heldout/) has been created with a strict protocol:
- verified content only;
- labelled before the classifier is run;
- frozen with a SHA-256 lock;
- never used for tuning;
- two annotators.

**It contains 0 items.** `python3 -m benchmark.run_benchmark --set heldout` refuses to report an accuracy figure and exits with code 2. The development benchmark (95% exact) remains tuning data, **not independent evidence**.

## Task 5 — Commercial feasibility

| # | Question | Result | Basis |
|---|---|---|---|
| 1 | Verified UK/UAE leads from the last 30 days | **0** | No source content retrievable |
| 2 | Actively seeking external providers (verified) | **0** | 19 title-only Tier A/B candidates, unverified, location unknown |
| 3 | Relevant to £1,000–£3,000 (verified) | **0** | No budgets observed |
| 4 | Permitted and practical contact route (verified) | **0** | Forum job posts invite replies by design. Tenders go through the procurement process. Forum terms for *collecting* data are still unconfirmed |
| 5 | False positives | **Not measurable.** No verified items and an empty held-out set | Among title-level candidates, the rules excluded 7 vendor, 7 recruitment, 5 unrelated/physical and 9 Tier D items. Dev-set false positives are documented in [intent-scoring.md](intent-scoring.md) |
| 6 | Collection and enrichment costs | **£0 spent.** Collection APIs are free (OGL / public JSON); Companies House is free | No credits bought. Projected running cost is unchanged: ≈ $20–150/month ([architecture.md](architecture.md#monthly-operating-cost-estimate)) |
| 7 | Source limitations and permissions | Network policy (ours); forum owner permission (not obtained); tenders mostly far above £3k; Upwork, Freelancer and Reddit not applied for | See [data-sources.md](data-sources.md) |
| 8 | Could it realistically produce 10 or more qualified leads per month? | **Unproven. Early indicators are negative for automated forum and tender sources alone** | See below |

**Why the indicators are negative (all title-level and unverified, so weak evidence):**
- Across 47 candidates gathered by searches aimed at UK/UAE buyers, **only one title names a UK place, and it reads as an agency sourcing builders. No UAE end-buyer appears in any title.**
- About 30% of the community-board results were vendors or recruitment.
- Several items are visibly old: "Community Archive" posts, low topic ids, and age claims of about 5 months in the search summaries.
- Every real automation tender found so far is far above £3k.

These indicators would be overturned by a single live run showing a real flow of fresh UK/UAE posts. That run is the next step.

### Human-assisted approach (evaluation design, not results)

No automated source could be run, so the human-assisted route has been built but **not yet measured**:

- `python3 -m signal_engine.validate capture --url … --title … --excerpt … --posted-at … --reviewer … --source human:linkedin` records a post that a person opened. It is stored as `human_verified`, then deduplicated, classified and qualified like any API item, and counted as genuine.
- **Proposed 2-week trial:** one reviewer spends 45 minutes a day on LinkedIn search (keyword alerts such as "recommend" + "automation" / "Zapier" / "CRM", UK and UAE filters), UK Business Forums, PeoplePerHour and relevant Facebook groups they belong to. Every candidate is captured through `capture`.
- **What to measure:** qualified leads per reviewer-hour, the tier mix, and replies.
- **Kill criterion:** fewer than 5 qualified leads per week after 2 weeks.

No numbers are claimed until that trial runs.

## Re-run when access works

```bash
cd poc
python3 -m signal_engine.validate all --days 30
python3 -m unittest discover -s tests
```

This writes `poc/out/validation/{probe.md, verify_log.jsonl, verified.jsonl, discovered.jsonl, leads.jsonl, funnel.json, lead_review.md}`. Then:
1. Manually review every Tier A/B record in `lead_review.md`.
2. Add fully read items to `benchmark/heldout/heldout.jsonl`, labelling them **before** looking at the classifier output.
3. Run `python3 -m benchmark.run_benchmark --set heldout --freeze`.

**Endpoints still to confirm on the first live run** (marked `unconfirmed` in the probe):
- the Contracts Finder `keyword` search parameter;
- the single-notice JSON endpoints for Contracts Finder and Find a Tender.

If either fails, `verify` records which one, and those tender candidates must be checked by hand.

## Restrictions honoured

- No Supabase tool or connection was used, and no request was sent to `api.supabase.com`.
- No database changes, no deployment, no purchases.
- No access control was bypassed: blocked requests were not retried through other routes.
- No data was invented. Only `rekuom/Solvant-Lead-Enginer` was changed.
