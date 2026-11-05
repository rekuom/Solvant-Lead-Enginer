# Intent scoring

Implementation: [`poc/signal_engine/classify.py`](../poc/signal_engine/classify.py). Benchmark: [`poc/benchmark/`](../poc/benchmark/).

## Principles

1. **Evidence or nothing.** Every tier is justified by phrases matched in the source text. Each match is stored as `evidence[].matched`, and a test asserts that every evidence string appears verbatim in the source. A high tier cannot come from our own inference.
2. **Negatives first.** Off-topic automation, vendor self-promotion and recruitment are checked *before* positive intent. The words "hiring", "automation" or "fixed price" alone can never produce a high tier.
3. **Intent ≠ actionability.** `intent_tier` describes what the text says. `actionable` is the outreach decision after the freshness, verification and fit gates.
4. **Conservative under uncertainty.** An unknown date caps the signal at C. Unverified content is held. A vague scope cannot reach A.

## Tiers

| Tier | Definition | Required evidence | Example (from the benchmark) |
|---|---|---|---|
| **A** | Explicitly seeking an **external** automation provider **with a project or budget** | external-help request **+** specific scope (*what* to automate, not just the word "automation") **+** budget, timeline, defined deliverable or formal procurement. Not ongoing staffing | "Looking to Hire an n8n Expert to Build a Lead Management Automation Workflow" |
| **B** | Actively requesting implementation help, without budget/project detail (or with a vague scope, or as ongoing capacity) | external-help request + automation scope | "Looking for a Make Expert to Build Copper CRM Automations" |
| **C** | A clearly described operational problem, with no request to hire | problem language (manual work, hours lost, pain) + automation-relevant scope | "Our team spends hours every week copying data from emails into spreadsheets" |
| **D** | General interest or weak inference. Also agency/partner sourcing and product-only tenders | automation/AI mention, partner wording, product procurement | "Healthcare AI Solutions" (tender); "…for our clients" |
| **Reject** | Recruitment or staffing, vendor self-promotion, unrelated or physical automation, outdated or closed, unverifiable | any hard-negative rule | "[For Hire] …", "JOB OFFER – full time", "quadruped robot" |

### Actionable gates (applied after the intent tier)

| Condition | Effect |
|---|---|
| `verification_status = synthetic` | `TEST_ONLY`. Never a lead |
| `verification_status = search_index_only` | `HOLD_VERIFY`. A human must open the URL and confirm the content, date and status |
| tender `deadline_at` in the past | `REJECT (closed)` |
| posted more than 90 days ago | `REJECT (outdated)` |
| posted 31–90 days ago | downgrade one tier |
| posting date unknown | cap at C |
| any value or budget | **no effect on tier.** Recorded as information; ≥ £100k equivalent sets `large_project_may_need_delivery_partner` and `partnership_opportunity` |
| location | from place evidence only ([markets.py](../poc/signal_engine/markets.py)); unknown → `location_unknown_review`, explicit non-target → `outside_target_markets` (excluded at qualification) |

### Score (0–100)

Each tier has a base score and a cap (A 80–100, B 62–79, C 42–59, D 18–34, Reject 0). Within the band, the score goes up with extra scope matches (+4 each), budget or project evidence (+5 each) and corroborating request phrases (+3 each). Scores never cross a tier boundary, so the score only ranks signals within a tier and cannot promote one.

### Service suggestion

Keyword-mapped service names: finance and invoicing automation, document processing, platform migration, recruitment pipeline, CRM integration, AI development and implementation, workflow builds on n8n / Make / Zapier / Power Automate, systems integration, lead capture, reporting, AI inbox and RPA. **No prices**: scope and budget are agreed per opportunity, at any size. Delivery complexity, delivery requirements and partnership need are separate informational flags. Queues and qualification: [live-validation.md](live-validation.md).

---

## Benchmark

`cd poc && python3 -m benchmark.run_benchmark`

- **62 items**: 36 **real** (verbatim search-index titles and URLs, labelled from title and URL slug only) and 26 **synthetic** hard cases (including the brief's example phrases and the main traps).
- **Gold labels:** one annotator. Two real items are labelled `UNCLEAR` and excluded from scoring.

### Results

| | v0 baseline | v1 (current) |
|---|---|---|
| Exact tier accuracy | 47/60 (78%) | 57/60 (95%) |
| Real items, exact | 23/34 (68%) | 31/34 (91%) |
| Synthetic items, exact | 24/26 (92%) | 26/26 (100%) |
| A/B precision | 0.95 | 1.00 |
| A/B recall | 0.91 | 0.95 |
| False positives (pred A/B, gold C/D/Reject) | 1 | 0 |
| False negatives (gold A/B, pred lower) | 2 | 1 |

Full per-item reports: [`results_v0-baseline.md`](../poc/benchmark/results_v0-baseline.md) and [`results_v1.md`](../poc/benchmark/results_v1.md).

> ⚠️ **The v1 numbers are optimistic.** The same 62 items were used to find and fix the v0 errors, and there is no held-out test set. Expect lower accuracy on unseen data. Phase 2 must build a held-out set of at least 200 verified items with two annotators.

### False-positive and error findings

**Errors found in v0 and fixed with general rules (not item-specific patches):**

> **v2 (2026-11-05, expanded scope):** 56/59 exact (95%), A/B precision 1.00, recall 0.95 ([results_v2.md](../poc/benchmark/results_v2.md)). One item, "Healthcare AI Solutions", was relabelled UNCLEAR because AI implementation is now in scope and its title can't tell product from services. Still development data, not independent proof.

| Item (real) | v0 | Gold | Cause | Fix |
|---|---|---|---|---|
| "Low Code No Code Platform" (Find a Tender) | B | D | Treated as procurement of services, but it buys a software *product* | Product-procurement rule for tenders |
| "Robotics Process Automation Tool" | Reject | D | The physical-robot regex matched "Robotics" | Exclude "robotic(s) process" from the physical rule |
| "Hiring: Sales Tech & Automation Specialist (Ongoing…)" | D | Reject | The job-title regex failed on "&" | Allow `& / + .` in titles |
| "Hiring: AI Growth & Automation Specialist" | D | Reject | Same cause | Same fix |
| "🚀 Hiring: Freelance AI Automation Engineer" | Reject | B | Job-title wording outweighed "Freelance" | "freelance / one-off / fixed-price" overrides job-title recruitment |
| "Healthcare AI Solutions" | Reject | D | General AI interest was not recognised | AI-interest → D |
| "Provision of RPA Services", "Intelligent Automation … Delivery Partner" | B | A | A tender was not treated as a defined project | Formal procurement counts as project evidence |

**Over-confidence on ambiguous titles (the most important false-positive risk):**
- "Workflow Automation for a fee" is predicted **A**. The title is ambiguous: it could be a buyer offering a fee or a freelancer selling work for a fee. Title-only data can't resolve this. The body is required.
- "Automation Contract" was predicted **A** in an intermediate version. It is now **B**, after the rule that Tier A needs a specific scope beyond the bare word "automation". It could still be building or industrial automation.

**Remaining v1 errors (left unfixed on purpose, to avoid overfitting):**
- "Looking For a Part-Time Automation Expert!" is predicted Reject, gold B. "Part-time" is treated as employment. This is conservative and costs one possible lead.
- "Build lead capture and booking automation Pro needed" is predicted B, gold A (under-scored, not a false positive).
- "AI Automation Engineer" is predicted D, gold Reject. The URL slug shows a job-seeker, but the classifier does not read slugs.

**Structural false-positive sources seen in real data:**
1. **Vendor posts imitate buyer language.** "[For Hire] … fixed price" has budget words. Vendors were 6 of 36 real results.
2. **Staffing looks like a budget.** "$75–$95/hr ongoing contractor work" has money but is capacity hiring.
3. **Agencies sourcing for their clients.** These are channel partners or competitors, not end buyers.
4. **"Automation" is overloaded.** Tenders for robots, tool rooms and building controls match a naive keyword search.
5. **Tenders that buy products, not services.** Platforms and licences.
6. **Closed or archived items.** The search summaries showed several tenders already past their deadlines and one post in the Make "Community Archive".

## Phase 2 classifier

- Keep this deterministic classifier as a **guard-rail**: hard negatives always win, and a high tier requires a rule-matched span.
- Add an LLM pass (structured output: tier, evidence spans *copied verbatim*, rationale, service). Reject any LLM output whose evidence spans are not found in the source text. If the LLM and the rules disagree by two or more tiers, send the item to human review.
- Track precision of Tier A/B on human-verified outcomes weekly. The target is 0.9 or higher before outreach volume increases.
