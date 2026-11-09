# Next phase requirement: private, cloud-based lead intake

**Status:** product requirement, recorded on 2026-11-09. **Not implemented. No database, Edge Function, secret or infrastructure change has been made.** Implementation requires separate, explicit approval.

## Requirement (from the product owner)
> I do not want to install Python or process marketplace alerts on my own computer.

The current intake (`python -m signal_engine.discovery.run intake …`) assumes a local machine with Python, and private storage on that disk. That doesn't meet this requirement. Intake must also not run in GitHub Actions of this **public** repository, because alert content is personal and commercially confidential.

## What the next phase must provide
1. **No local software.** The owner adds leads from a browser or phone, or by forwarding e-mails. No Python, CLI or downloads are needed.
2. **User-authorised alert ingestion in the cloud.** Marketplace alert e-mails (Upwork, Freelancer, PeoplePerHour, Malt, Fiverr Briefs) are forwarded by the owner to a private intake address or uploaded through a private form. Parsing reuses the existing, tested logic (per-project splitting, platform rules, `user_submitted` verification, fixtures never counted as leads).
3. **Manual capture and verification.** A private form for URL, post date, text and reviewer initials, which produces `reviewer_verified` exactly like `intake add --verified-by`.
4. **Private storage only.** Records go to the dedicated Solvant Supabase project (`dfnaevcsergsphiiodtm`), never to the repository, Actions logs, summaries or artifacts. Row-level security allows no anonymous access, and the owner and reviewers sign in.
5. **Same compliance rules.** No scraping, no automated proposals or outreach, in-platform contact only where platform rules require it, retention and deletion handling, and Brave output never stored without attested storage rights.
6. **Assessment and routing reuse.** The existing assessment, pipelines and ranking run on cloud-ingested records. Discovery outputs from Actions can be pushed to the same private store through the authenticated ingest path already proposed in `operations.md` §4.

## Proposed shape (for approval; not built)
- **Storage:** schema `signal` from [`supabase-schema-proposal.sql`](supabase-schema-proposal.sql), extended with an `intake_submissions` table that holds the raw alert, encrypted at rest and with a short retention period.
- **Ingest:** a Supabase Edge Function `ingest-intake`. It is authenticated (signed-in owner, or an inbound-email webhook secret), validates input (`https://` URLs, permitted source, size limits) and treats content as untrusted data.
- **E-mail route:** an inbound-email provider webhook to the Edge Function. Choosing a provider is a separate decision with its own cost and terms review.
- **Parsing:** the alert parsers ported from `poc/signal_engine/discovery/intake.py`. Either rewrite them in TypeScript for the Edge Function, or run Python in a private worker. Decide at design review. The existing fixtures and tests become the acceptance suite.
- **UI:** a minimal private intake form and review list. This is not the full dashboard, which still needs separate approval.

## Approvals needed before any implementation
- Applying the schema migration to `dfnaevcsergsphiiodtm`.
- Creating Edge Functions and their secrets.
- Choosing and paying for an inbound-email provider, if the e-mail route is wanted.
- The data-retention period for raw alerts and excerpts.

## Explicitly out of scope until approved
Any Supabase connection, migration, function deployment or secret creation; any purchase; any automated outreach.
