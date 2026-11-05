# Phase 1 feasibility report

Date: 2026-11-05 · Branch: `claude/trusting-hawking-kqus6b`

> **Update (Phase 2A, 2026-11-05):** the allowed domains were still blocked by this session's network policy. 0 items verified. See [validation-2a.md](validation-2a.md).

## Bottom line

**Conditional GO.** The engine can be built on legal, free and authorised data. The classification approach works on real titles. But Phase 1 could not prove there is **enough UK/UAE buyer volume at £1–3k** from sources we are allowed to collect automatically. That is the deciding question. Phase 2 must start with a 1–2 week live validation (see [phase-2-plan.md](phase-2-plan.md)) before any build spend.

- **Genuine verified signals collected: 0.** No source host could be reached from this cloud session (network policy). Nothing was fetched directly, so nothing can honestly be counted as verified.
- **Real candidate items discovered through a search index: 36** (real URLs and verbatim titles). The rules classifier rates **14 as plausible buyer requests** (5 Tier A, 9 Tier B by title), 6 as Tier D and 16 as Reject. **All 36 are HOLD_VERIFY**, because their bodies, dates and status have not been seen.
- **Target of 50 genuine signals: not met.** The real number is 0 verified and 14 unverified plausible candidates. The UK/UAE share among them is unknown, and probably small.

## What was actually tested

| Test | Result |
|---|---|
| Direct HTTPS from the container to 22 source hosts (Reddit, HN Algolia, Stack Exchange, Contracts Finder, Find a Tender, Freelancer, Upwork, PeoplePerHour, TheirStack, LinkedIn, Facebook Graph, Zapier/Make/n8n communities, UK Business Forums, Dubai eSupply, Guru, etc.) | **All refused**: HTTP 403 at the environment's egress proxy (`connect_rejected`, policy denial). No request reached any source |
| Server-side page fetch (WebFetch) for `hn.algolia.com`, `www.contractsfinder.service.gov.uk` | **Refused** (DNS not allowed for this session). Stopped after two, as instructed by the tool |
| Web search (index results only) | **Works**, except reddit.com, which refuses this crawler. Used for discovery and documentation research only |
| PoC pipeline (dedupe → classify → JSONL) on the real search candidates and synthetic parser fixtures | **Works.** 27/27 unit tests pass |
| Live collector code path (`--live contracts_finder`) | Executed for real. It reported `contracts_finder: BLOCKED — Tunnel connection failed: 403 Forbidden` and produced no records. Parsing of real API responses is therefore **untested**: parsers are unit-tested only against synthetic OCDS/Discourse-shaped fixtures |
| Classifier benchmark (62 items: 36 real titles, 26 synthetic) | v1: 95% exact tier, A/B precision 1.00, recall 0.95. **Optimistic**: no held-out set (see [intent-scoring.md](intent-scoring.md)) |

**To unblock live testing,** allow the source hosts under the cloud environment's network settings (Network access → Allowed domains; steps: https://code.claude.com/docs/en/cloud-environments#network-access), or run the PoC on a local machine. Start with `www.contractsfinder.service.gov.uk`, `www.find-tender.service.gov.uk`, `community.n8n.io` and `community.make.com`.

## Which sources work

Details are in [data-sources.md](data-sources.md). In short:

| Works legally and technically (pending live run) | Works only as an on-platform channel | Blocked or manual only |
|---|---|---|
| Contracts Finder, Find a Tender (OGL, free) | Upwork API (key approval), Freelancer API | Reddit (commercial approval needed), LinkedIn, Facebook groups, UAE tender portals, PeoplePerHour |
| Companies House, TheirStack (enrichment) | | n8n and Make communities (technically open; **permission needed** for commercial collection) |

## Key findings

1. **The demand that exists is in the wrong places for automation.** Explicit, budgeted automation requests concentrate in freelance marketplaces (terms forbid moving buyers off-platform) and tool communities (global, many agencies). LinkedIn and Facebook are where UK/UAE SMEs are, and both forbid automated collection.
2. **Public tenders are real but wrong-sized.** Real automation tenders found were £150k–£38m. £1–3k public purchases are generally not advertised.
3. **The open web is mostly vendors.** A web search for buyer phrasing ("looking for someone to automate" invoicing UK) returned only vendor pages, software guides and Fiverr gigs: zero buyer posts.
4. **False positives are structural and catchable.** Vendor "[For Hire]" posts, staffing ("$75–95/hr ongoing"), job offers, agencies sourcing for their clients, physical-automation tenders and product-only tenders all imitate buying signals. The rules catch them. In the real titles, 16 of 36 were correctly rejected.
5. **Title-only evidence is not enough.** Two real titles are genuinely ambiguous (for example "Workflow Automation for a fee"). The body, date and status are required before outreach. The pipeline enforces this with `HOLD_VERIFY`.

## Costs

Expected Phase 2 running cost is **≈ $20–$150/month** (≈ £15–£120), excluding Reddit (negotiated) and an optional Sales Navigator seat. The breakdown is in [architecture.md](architecture.md#monthly-operating-cost-estimate). Phase 1 incurred **£0**: no paid services, no deployments and no database changes.

## Blockers and limitations

- The session network policy blocks all source hosts, so there are zero verified signals.
- Reddit commercial access and Upwork API access need applications and approval (weeks).
- Community-forum collection needs owner permission.
- Single-annotator benchmark, labelled from titles, with no held-out set.
- Some facts are from prior knowledge and are marked "re-verify" in data-sources.md: thresholds, the Facebook Groups API deprecation, Upwork RSS removal, LinkedIn terms.
- The OCDS notice-URL mapping and the response shape are written to the OCDS standard but not yet confirmed against a live response.
- A legitimate-interests assessment (UK GDPR) and a UAE PDPL review are not yet done. They are required before storing forum handles at scale.

## Recommendation

**Conditional GO.** Run Phase 2a (live validation plus access applications) first. Proceed to build only if it shows **10 or more verified, fresh UK/UAE Tier A/B signals per month** from permitted sources, or Upwork/Freelancer API access is granted. Otherwise pivot to a manual-assisted capture, classify and CRM tool, which still has value and needs no restricted data.
