# Phase 4: multi-source customer-acquisition intelligence

Branch `claude/phase4-multisource-discovery` (not merged; awaiting review).

| Document | Contents |
|---|---|
| [source-registry.md](source-registry.md) | 41 sources with access and permission findings, ranked source families, lead-marketplace comparison |
| [architecture.md](architecture.md) | Connectors, intake, dimensions A–J, pipelines A–H, ranking profiles, privacy and compliance, cost control, LLM estimate |
| [experiments.md](experiments.md) | Actual results of experiments A–F |
| [supabase-schema-proposal.sql](supabase-schema-proposal.sql) | Proposed schema (not applied) |
| [dashboard-and-crm-spec.md](dashboard-and-crm-spec.md) | Dashboard and CRM functional spec |
| [operations.md](operations.md) | **Brave key setup and non-retention, verification routes (which hits can become leads), marketplace alert setup, temporary vs persistent data, private storage design, first-run parameters, PR checks** |
| [roadmap.md](roadmap.md) | Commercial recommendation, cost and feasibility, rollout, blockers |

## Status of each capability

| Capability | Working | Tested | Real-data tested | Blocked by |
|---|---|---|---|---|
| Source registry and policy gating | ✅ | ✅ unit | — | — |
| GitHub Issues connector | ✅ | ✅ unit | ✅ 134 records (Claude Cloud) | — |
| GitHub Discussions (GraphQL) | ✅ code | ✅ code path | ❌ | GraphQL blocked in Claude Cloud; runs in Actions (untested) |
| HN connector incl. "Seeking freelancer" | ✅ code | ✅ unit | ❌ | Restricted: terms review + opt-in |
| Open-web search (Brave adapter) | ✅ code, checked against API reference | ✅ stubs/fixtures | ❌ | Your key; storage-rights terms |
| Brave non-retention (in-memory, counts only, attestation gate) | ✅ | ✅ regression tests incl. duplicates | — | — |
| Search-hit verification via original APIs (GitHub, Find a Tender, HN opt-in) and manual `--verified-by` | ✅ | ✅ unit | ✅ GitHub (earlier run) | — |
| PR checks (`pr-checks.yml`, `scripts/policy_check.py`) | ✅ | ✅ | — | — |
| RSS/Atom connector | ✅ | ✅ unit | ❌ | No feed with verified terms registered |
| Multilingual query library and planner | ✅ | ✅ unit | ✅ (GitHub, English) | Non-English phrases need native review |
| Marketplace / manual / e-mail / licensed intake | ✅ | ✅ unit | ❌ | Owner must supply alerts or captures |
| Assessment A–J + new noise detectors | ✅ | ✅ unit + real run | ✅ GitHub | Independent review pending |
| Pipelines and ranking profiles | ✅ | ✅ unit | ✅ GitHub | — |
| Stage audit, no silent cap | ✅ | ✅ unit | ✅ | — |
| Blind review packet and scoring | ✅ | ✅ code | ❌ | Needs ≥20 real items and a human reviewer |
| Procurement pipeline (E) | ✅ | ✅ | ✅ (Phase 3 held-out) | Not independently validated |
| Workflow `multi-source-discovery.yml` | ✅ | ✅ simulated locally | ❌ | You click **Run** |
| Supabase schema | Proposal | — | — | Approval |
| Dashboard | Spec | — | — | Approval after evidence |

## Run it
```bash
cd poc
python3 -m signal_engine.discovery.run sources
python3 -m signal_engine.discovery.run discover --sources github_issues --since-days 45 --max-requests 20
python3 -m signal_engine.discovery.run intake email alerts/upwork-alert.eml
python3 -m signal_engine.discovery.run intake add --source-key linkedin --url https://… --post-date 2026-11-05 --text "…" --stated-role founder --verified-by RM
python3 scripts/policy_check.py
python3 -m signal_engine.discovery.run report
python3 -m signal_engine.discovery.run review-packet --pipeline A_DIRECT_SME --top 20
```
In GitHub: **Actions → Multi-source discovery → Run workflow**.
