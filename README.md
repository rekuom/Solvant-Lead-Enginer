> **Platform:** the Solvant Signal Engine web application, database and deployment guide are in [docs/platform/README.md](docs/platform/README.md).

# Solvant Signal Engine

Buying-intent intelligence for [Solvant.io](https://solvant.io). It finds organisations in the **UK, UAE and all of Europe** that are **actively looking for an external provider** for AI development, AI agents, workflow automation (n8n, Make, Zapier, Power Automate), CRM and finance automation, document processing and systems integration. **No budget minimum or maximum**: budget is recorded, never used to exclude. Weaker evidence, such as general complaints, internal recruitment and vendor self-promotion, is separated out and explained.

**Status: live validation ready.** Run it manually from GitHub Actions: [docs/live-validation.md](docs/live-validation.md). No app, no database writes, no deployments.

## Documents

| Doc | Contents |
|---|---|
| [docs/feasibility.md](docs/feasibility.md) | What was tested, results, go/no-go |
| [docs/data-sources.md](docs/data-sources.md) | Per-source legality, API, coverage, cost, freshness |
| [docs/intent-scoring.md](docs/intent-scoring.md) | Tiers A–D/Reject, gates, benchmark and false-positive analysis |
| [docs/architecture.md](docs/architecture.md) | Next.js + Supabase target design, RLS, privacy, rate limits, costs |
| [docs/phase-2-plan.md](docs/phase-2-plan.md) | Validation step, exit criteria, build plan |
| [docs/validation-2a.md](docs/validation-2a.md) | Phase 2A live validation: access probe, funnel, qualification, held-out set |
| [docs/live-validation.md](docs/live-validation.md) | **Current rules**, markets, source permissions, queues, how to run the GitHub workflow |
| [docs/phase4/README.md](docs/phase4/README.md) | **Phase 4**: multi-source discovery, source registry, pipelines A–H, intake, experiments, schema & dashboard spec |
| [docs/classification-quality.md](docs/classification-quality.md) | Root-cause audit of run 42174857442, service-relevance filter, real held-out results |

## Proof of concept (`poc/`)

Stdlib-only Python 3.11+. Nothing to install.

```bash
cd poc
python3 -m unittest discover -s tests -v          # 127 tests
python3 -m signal_engine.discovery.run sources     # Phase 4 source registry
python3 -m benchmark.run_real_eval --split heldout   # quality gate on real, manually labelled records
python3 -m signal_engine.validate permissions     # which collectors are permitted
python3 -m signal_engine.validate live --days 30 --max-records 100   # permitted sources only → CSV + Markdown
python3 -m benchmark.run_benchmark                # dev benchmark (62 items, used for tuning)
python3 -m benchmark.run_benchmark --set heldout  # independent held-out set (currently empty)
python3 -m signal_engine.pipeline --candidates data/search_candidates_2026-11-05.json
python3 -m signal_engine.pipeline --fixtures fixtures   # synthetic parser fixtures
# Live collection (needs network access to the hosts; blocked in the Phase 1 cloud session):
python3 -m signal_engine.pipeline --live contracts_finder,find_a_tender --since 2026-10-06
```

Output: `poc/out/signals.jsonl` (one record per signal: source URL, excerpt, timestamps, tier, score, evidence, reasons, suggested service) and `poc/out/summary.json`. `poc/out/` is git-ignored.

```
poc/
  signal_engine/
    models.py           Signal + verification status (verified_api / search_index_only / synthetic)
    textutil.py         HTML strip, PII redaction, URL canonicalisation, fingerprints
    dedupe.py           URL / source-id / content-hash / near-duplicate dedupe
    classify.py         evidence-based tiering, gates, service suggestion
    pipeline.py         CLI: collect → dedupe → classify → JSONL
    probe.py            access probe: proxy block vs upstream refusal vs auth vs rate limit
    markets.py          target markets (UK, UAE, Europe) + place-evidence location detection
    sources.py          source permission registry (collectors gated on it)
    relevance.py        service relevance of the deliverable (separate from buying intent)
    qualify.py          queues: Priority A/B/C, watchlist, excluded, unverified (budget = info only)
    validate.py         Phase 2A CLI: probe / verify / discover / report / capture
    collectors/
      http.py           polite client (UA, robots.txt, rate limit)
      ocds.py           Contracts Finder + Find a Tender (OCDS)
      discourse.py      n8n / Make community boards (DISABLED: permission not obtained)
      ted.py            EU TED Search API v3
      search_candidates.py  loader for search-discovered URLs (unverified)
  data/                 real search-discovered candidates (titles + URLs only)
  fixtures/             SYNTHETIC parser fixtures, never counted as leads
  benchmark/            gold labels, runner, results v0 and v1
  tests/
```

## Honesty rules built into the code

- Only `verified_api` records (fetched by the pipeline from an official source) count as genuine signals.
- Search-discovered items are always `HOLD_VERIFY`. Synthetic fixtures are always `TEST_ONLY`.
- Every tier carries the matched source phrases as evidence.
- Emails and phone numbers are stripped at ingestion.
