# Dashboard and CRM: functional specification (not built)

Status: specification only. Build only after evidence review and approval. Data model: [`supabase-schema-proposal.sql`](supabase-schema-proposal.sql).

## Navigation
1. **Overview**
2. **Pipelines:** A Direct SME, B Freelance, C Agency, D Pain, E Procurement, F Recruitment, G Licensed, H Research, Global review
3. **Review queue:** blind labelling
4. **Sources:** registry, permissions, performance
5. **Settings:** markets, languages, queries, caps

## Overview (wireframe)
```
┌ New today ┐┌ Verified buying requests ┐┌ Direct SME ┐┌ Freelance ┐┌ Agency ┐┌ Pain ┐┌ Tenders ┐┌ Needs review ┐
└───────────┘└──────────────────────────┘└────────────┘└───────────┘└────────┘└──────┘└─────────┘└──────────────┘
Source performance (table): source · opportunities · verified · contactable · conversations · proposals · wins · revenue · cost · revenue/source
Last runs: run id · sources · status (failed connectors in red) · requests · est./actual cost
```
Every number links to its rows. There's no single "lead score" across pipelines; each pipeline tab ranks with its own profile.

## Lead detail
- **Facts:** buyer or company, original source and **original URL**, date (with the date-evidence note), country and location evidence, industry, company size **with basis** (registry / website / self-reported / estimated).
- **Assessment:** exact need, buying-intent evidence (quoted), technical relevance with evidence for and against, suggested Solvant solution, delivery complexity and flags.
- **Contact:** permitted contact route, outreach restrictions (e.g. "in-platform only", "formal tender"), confidence, missing facts.
- **Sales:** priority, stage, notes, history.

Raw evidence and the classifier's interpretation are shown in **separate panels**.

## Actions
| Action | Effect | Guard |
|---|---|---|
| Save / Verify | `verification → reviewer_verified` after the reviewer confirms the URL, content and date | Requires opening the original URL (link-out is recorded) |
| Assign | Sets the owner | — |
| Reject with reason | `stage=rejected` + a reviewer correction (feeds evaluation) | Reason required |
| Mark contacted / replied / qualified / proposal sent / won / lost | `sales_activities` rows | "Contacted" only if `outreach_permissions.allowed` |
| Record project value / acquisition cost | `sales_activities.value_amount` / `acquisition_costs` | — |
| Follow-up | Due date and reminder | — |
| Export approved leads | CSV of verified, permitted rows only | Excludes suppressed rows; logged |
| Review duplicates | Merge or keep | — |

**No action ever sends a message automatically.**

## Business intelligence
Sources are ranked on **outcomes, not volume**:
- opportunities, verified, contactable;
- conversations, proposals, wins, revenue;
- acquisition cost and time spent;
- revenue per source and per hour.

## Review workflow
The blind review shows source evidence only (no model labels). Labels feed `reviews`, and the dashboard reports Precision@10/@20 per pipeline and per source family, with denominators.

## Access
Supabase Auth, internal users only. Roles: `reviewer` (read and label), `sales` (pipeline stages on assigned leads), `admin` (sources, settings, exports). RLS on every table, no anonymous access, and the service role is used only by collectors on the server side.
