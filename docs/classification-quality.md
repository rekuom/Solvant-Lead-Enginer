# Classification quality fix (after live run 42174857442)

Date: 2026-11-06. Evidence: artifact `live-lead-report-42174857442`, downloaded and inspected record by record.

## 1. Root-cause audit

The run fetched 1,383 records and kept 100 (42 Priority A, 23 Priority B). A manual review of those 100 found **only 21 of the 65 Priority A/B records were relevant, and none of the top 20 were**.

| # | Cause (exact rule) | Effect seen in the run |
|---|---|---|
| 1 | `classify.py`: every tender automatically received `public_tender` (external-provider evidence) **and** `tender_project` (project evidence) | Any tender with one scope-word match became Tier A, so procurement intent was treated as service relevance |
| 2 | Generic scope regexes: `\bintegrat\w*\b`, `\breports?\b`/`reporting`, `\bautomat\w*\b`, `outreach`, `onboarding`, `\bexcel\b`, bare `\bcrm\b`, `\bapi\b` | "Integrated care", "report for each property" (gutters), "automatic doors", "automated wash line" (laundry), "Scotland Excel", "outreach" services, CRM = cardiac rhythm management / certified reference material / a radar model |
| 3 | These generic hits also counted as "specific scope", which defeated the Tier-A guard | Construction and care contracts reached Tier A |
| 4 | Score added `+5` per budget/project item, including `tender_value` and `tender_project` | The biggest irrelevant contracts ranked highest (£250m housing, £203m urgent care) |
| 5 | Contracts Finder `keyword` parameter is silently ignored by the API | 11 "keyword" calls returned the same 100 notices (1,100 fetched, 1,037 duplicates): an unfiltered feed of every UK tender |
| 6 | TED full-text keyword `"CRM"` | Matched medical consumables ("MicroPort CRM"), reference substances and radar |
| 7 | Cap applied after a queue sort, and the artifact held only the 100 kept records | The 250 dropped records were all in the EXCLUDED queue (every A/B/Watchlist record was kept). Their content is not in the artifact, so it can't be proven that no relevant non-English tender was among them. Now fixed: the uncapped `all_records.jsonl` is uploaded |
| 8 | Guessed Contracts Finder single-notice endpoint; no 429 handling | Verify step: 4× HTTP 404 and 2× HTTP 429 |

## 2. Fix: procurement intent kept separate from service relevance

New module [`relevance.py`](../poc/signal_engine/relevance.py) judges the **deliverable**, independently of buying intent:

- **Verdicts:**
  - `relevant`: software, AI, automation, CRM, integration or digital-system *services*.
  - `product_only`: licence, subscription, renewal or COTS product with no service scope.
  - `not_relevant`.
  - `uncertain`: always sent to human review.
- **Positive evidence must be specific.** Recognised: AI/ML (in 14 languages), chatbots and assistants, process/workflow automation, Power Platform, low-code, n8n/Zapier/Make, the CRM *software* sense, integration platforms/ESB/API work, software development, document processing and data extraction, plus business-automation phrases from direct buyer posts.
- **Generic words never count:** integrated, report(ing), automatic, automated, service, system, solution, platform, digital.
- **Acronym traps are resolved from context:**
  - CRM: cardiac rhythm management, certified reference material, radar models, consumables.
  - API: active pharmaceutical ingredient.
- **Hard negative domains:** construction and works, cleaning and laundry, care and clinical services, hardware and equipment (including "for AI research"), industrial control (MCC/ICA/SCADA), staffing, marketing, energy and nuclear.
- **Official classification codes are used:**
  - TED's English CPV label (the "Country – CPV label – title" prefix).
  - CPV codes when the source provides them (now stored for OCDS too).
  - A non-IT CPV label with no software evidence counts as evidence against.
  - An IT CPV label with an unclear description gives `uncertain`, not relevant.
- **Uncertainty is recorded explicitly**, for example "non-English text … technical requirement not understood reliably".

**Tenders:**
- The tier comes from relevance.
- Tender value and "it is a tender" no longer raise the score.
- A relevant tender is **Priority B at most**, with "formal tender: confirm procedure, eligibility, lots and submission route", because a published notice isn't an immediately contactable buyer.
- The procurement stage is recorded (`competition_open`, `pre_procurement`, `award_or_modification`, …). Award and modification notices are excluded.

**Ranking and cap:** sort by queue → relevance → evidence score, then cap. Relevant records now always come before irrelevant ones, and all genuine records are kept in `all_records.jsonl`.

**Budget:** still unrestricted and informational. **Markets:** still UK, UAE and all of Europe.

## 3. Real-record evaluation

[`poc/benchmark/real_2026-11-06/`](../poc/benchmark/real_2026-11-06/) holds all 100 retained records with manual labels:
- gold relevance (R / P / N / U);
- actual deliverable;
- delivery route (direct / partner / vendor);
- procurement stage;
- prerequisites and notes.

The labels were written **before** the relevance filter existed. The split is deterministic by URL hash: **dev 45** (used for tuning) and **held-out 55** (frozen with `heldout.lock`, SHA-256 `b0e663b1…`, and never used for tuning). The held-out evaluation was run once, after the classifier was final.

### Held-out results (`results_heldout.md`)

| Metric | Old classifier (as run) | New |
|---|---|---|
| Precision of surfaced leads (Priority A/B), top 10 | — | **9/10 (90%)** |
| Precision of surfaced leads (Priority A/B), all | 13/37 (35%) | **14/15 (93%)** |
| Precision@10, full ranking (strict R) | 0/10 | 9/10 (90%) |
| Precision@20, full ranking (strict R) | 5/20 (25%) | 14/20 (70%), max possible 18/20 because only 18 R exist |
| Precision@20, full ranking (R or software product) | — | 19/20 (95%) |
| False-positive rate (non-R placed in A/B) | 24/37 (65%) | **1/37 (3%)** |
| Relevant records missed (relevance error) | — | 2 of 18 |
| Relevant, correctly excluded as awarded | — | 2 |

**The reported false-positive categories:** gutter/roof, bridge, laundry, urgent and live-in care, and medical consumables "CRM" are all **excluded** in the held-out evaluation.

**Remaining errors (not fixed after the held-out run, to keep it independent):**
- **False positive:** "ATU Student Work Placement Software System". This is a vertical SaaS product (gold P) that the filter treated as services, because "supply, implementation and support" contains service words.
- **Miss:** Slovak "SAP licence support plus SAP ERP operational support and development". The Slovak service words (*služby podpory, rozvoja*) aren't recognised, so the licence words won and it was marked product-only.
- **Miss:** NHS "automated digital MSK single point of access tool". The clinical vocabulary dominated and nothing matched "digital tool" development.

### Quality gate (≥ 90% service relevance in the top 20)

- **Surfaced leads: met.** 93% of Priority A/B are relevant, but the held-out split only produces **15** leads, not 20.
- **Full top-20 ranking: not met under the strict definition (70%).** The ceiling is 90% because the split has only 18 relevant records. The lenient figure, counting software products, is 95%.
- **Conclusion:** the gate **can't be conclusively passed on 55 records.** The next step is a fresh live run, with the top 20 labelled by a person who isn't involved in tuning.

### Limitations, stated plainly

- **Single annotator:** Claude, the same agent that wrote the filter. The labels were fixed before the filter existed, but the annotator had read all 100 records, so the held-out set is independent of *tuning iterations*, not of the author's knowledge. A human second annotation is needed.
- **Small sample:** 55 held-out records, mostly tenders (the forum sources are disabled for permission). Confidence intervals are wide.
- **No CPV codes in the dataset:** the 100 records were captured before CPV storage was added, so real runs will have *more* evidence than this evaluation used.
- **No independent proof from the synthetic and paraphrased tests.** They're regression guards only (`tests/test_relevance.py`).

## 4. Reproduce

```bash
cd poc
python3 -m unittest discover -s tests            # 89 tests
python3 -m benchmark.run_real_eval --split dev
python3 -m benchmark.run_real_eval --split heldout   # refuses to run if heldout.jsonl was edited
```

Attribution: contains public sector information licensed under the Open Government Licence v3.0, and TED notice data © European Union (excerpted and classified).
