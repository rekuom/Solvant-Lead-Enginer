-- Solvant Signal Engine — core schema (non-destructive: creates only; never drops or alters existing objects).
-- Target: dedicated Supabase project dfnaevcsergsphiiodtm, schema public.
-- Design reference: docs/phase4/supabase-schema-proposal.sql (reviewed, not trusted verbatim).
-- Privacy: the repository is public; this file contains structure only, never data about people.

create extension if not exists pg_trgm with schema extensions;

-- ----------------------------------------------------------------------------- enums
do $$ begin
  create type public.app_role as enum ('admin', 'editor', 'viewer');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.sales_stage as enum ('discovered', 'needs_review', 'verified', 'qualified', 'contact_planned', 'contacted',
    'replied', 'meeting_scheduled', 'proposal_sent', 'negotiation', 'won', 'lost', 'archived');
exception when duplicate_object then null; end $$;

-- ----------------------------------------------------------------------------- people using the app
create table if not exists public.members (
  user_id      uuid primary key references auth.users (id) on delete cascade,
  role         public.app_role not null default 'viewer',
  display_name text check (char_length(display_name) <= 80),
  created_at   timestamptz not null default now()
);
comment on table public.members is 'Application members. Being signed in is NOT enough: only members can read lead data.';

create table if not exists public.admin_bootstrap (
  id         uuid primary key default gen_random_uuid(),
  code_hash  text not null,
  expires_at timestamptz not null,
  used_at    timestamptz,
  used_by    uuid references auth.users (id) on delete set null
);
comment on table public.admin_bootstrap is 'One-time codes that let the owner claim the first admin seat. No policies: unreadable via the API.';

create table if not exists public.app_settings (
  key        text primary key check (key ~ '^[a-z0-9_]{2,60}$'),
  value      jsonb not null,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users (id) on delete set null
);

-- ----------------------------------------------------------------------------- sources and collection
create table if not exists public.sources (
  key                  text primary key check (key ~ '^[a-z0-9_]{2,80}$'),
  name                 text not null,
  family               text not null,
  permission_status    text not null check (permission_status in ('permitted', 'restricted', 'manual_only', 'licensed', 'unknown', 'prohibited')),
  collection_mode      text not null,
  connector            text,
  enabled              boolean not null default false,
  automated            boolean not null default false,
  paid                 boolean not null default false,
  export_allowed       boolean not null default false,
  pipelines            text[] not null default '{}',
  contact_route        text,
  notes                text,
  requirements         text,
  schedule_cron        text,
  monthly_budget_usd   numeric(10, 2) not null default 0 check (monthly_budget_usd >= 0),
  rate_limit           text,
  last_run_at          timestamptz,
  last_success_at      timestamptz,
  last_error           text,
  last_status          text,
  next_run_at          timestamptz,
  config               jsonb not null default '{}'::jsonb,
  review_date          date,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  -- restricted / unknown / prohibited / paid sources can never be switched on for automated collection here
  constraint sources_enable_guard check (
    not (enabled and automated and (permission_status in ('unknown', 'prohibited') or (paid and monthly_budget_usd = 0)))
  )
);

create table if not exists public.discovery_runs (
  id              uuid primary key default gen_random_uuid(),
  source_key      text references public.sources (key) on delete set null,
  origin          text not null check (origin in ('github_actions', 'web_intake', 'inbound_email', 'manual', 'scheduler')),
  external_run_id text,
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  status          text not null check (status in ('ok', 'partial', 'failed', 'skipped', 'running')),
  requests        integer not null default 0,
  records         integer not null default 0,
  new_records     integer not null default 0,
  failed_requests integer not null default 0,
  est_cost_usd    numeric(10, 4) not null default 0,
  actual_cost_usd numeric(10, 4),
  error_kind      text,
  detail          jsonb not null default '{}'::jsonb   -- counts only; never URLs/snippets of non-retainable sources
);
create index if not exists discovery_runs_source_idx on public.discovery_runs (source_key, started_at desc);

create table if not exists public.search_queries (
  query_id         text primary key,
  provider         text not null,
  category         text,
  market           text,
  lang             text,
  query            text not null,
  runs             integer not null default 0,
  verified_results integer not null default 0,
  last_run_at      timestamptz
);

-- ----------------------------------------------------------------------------- companies and leads
create table if not exists public.companies (
  id              uuid primary key default gen_random_uuid(),
  name            text not null check (char_length(name) between 1 and 200),
  normalized_name text generated always as (lower(regexp_replace(name, '[^A-Za-z0-9]+', '', 'g'))) stored,
  country         text,
  org_type        text,
  website         text check (website is null or website ~ '^https://'),
  size_estimate   text,
  size_verified   boolean not null default false,
  notes           text,
  created_at      timestamptz not null default now()
);
create unique index if not exists companies_normalized_uq on public.companies (normalized_name, coalesce(country, ''));

create table if not exists public.opportunities (
  id                    uuid primary key default gen_random_uuid(),
  canonical_url         text not null unique,
  fingerprint           text,
  source_key            text not null references public.sources (key),
  source_id             text,
  url                   text not null check (url ~ '^https://'),
  title                 text not null default '',
  requirement_summary   text,                 -- source fact (excerpt), never AI text
  body_excerpt          text,                 -- PII-redacted excerpt as obtained
  published_at          timestamptz,
  discovered_at         timestamptz not null default now(),
  last_seen_at          timestamptz not null default now(),
  source_state          text,
  country               text,
  location              text,
  org_type              text,
  organisation          text,                 -- only when the source states it
  company_id            uuid references public.companies (id) on delete set null,
  technologies          text[] not null default '{}',
  budget_text           text,
  verification          text not null check (verification in ('api_verified', 'reviewer_verified', 'user_submitted', 'licensed_import', 'search_snippet_only')),
  verified_by           uuid references auth.users (id) on delete set null,
  verified_at           timestamptz,
  buying_intent         text,
  technical_relevance   text,
  engagement_type       text,
  business_type         text,
  decision_maker_access text,
  freshness             text,
  contact_permission    text,
  contact_route         text,
  delivery_complexity   text,
  commercial_potential  text,
  evidence_confidence   text,
  priority              text check (priority in ('A', 'B', 'C')),
  pipeline              text not null check (pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER', 'D_OPERATIONAL_PAIN',
                          'E_PROCUREMENT', 'F_RECRUITMENT_SIGNAL', 'G_LICENSED_LEADS', 'H_RESEARCH_UNVERIFIED', 'GLOBAL_REVIEW', 'EXCLUDED')),
  pipeline_reason       text,
  rank_score            integer not null default 0,
  suggested_service     text,
  stage                 public.sales_stage not null default 'discovered',
  owner_id              uuid references auth.users (id) on delete set null,
  follow_up_at          timestamptz,
  deal_value            numeric(12, 2) check (deal_value is null or deal_value >= 0),
  deal_currency         text check (deal_currency is null or deal_currency ~ '^[A-Z]{3}$'),
  won_at                timestamptz,
  lost_reason           text,
  win_reason            text,
  duplicate_of          uuid references public.opportunities (id) on delete set null,
  acquisition_cost      numeric(10, 2) check (acquisition_cost is null or acquisition_cost >= 0),
  query_id              text,
  discovered_via        text,
  origin                text not null default 'discovery' check (origin in ('discovery', 'web_intake', 'inbound_email', 'csv', 'manual')),
  retain_until          timestamptz,
  meta                  jsonb not null default '{}'::jsonb,
  created_by            uuid references auth.users (id) on delete set null,
  updated_at            timestamptz not null default now(),
  search                tsvector generated always as (
                          to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(requirement_summary, '') || ' ' ||
                                      coalesce(body_excerpt, '') || ' ' || coalesce(organisation, ''))) stored,
  -- Brave Data-for-Search/AI output may never be retained; only original-source records are stored
  constraint opportunities_no_brave check (source_key <> 'web_search_brave')
);
create index if not exists opportunities_pipeline_idx on public.opportunities (pipeline, rank_score desc);
create index if not exists opportunities_stage_idx on public.opportunities (stage);
create index if not exists opportunities_discovered_idx on public.opportunities (discovered_at desc);
create index if not exists opportunities_source_idx on public.opportunities (source_key);
create index if not exists opportunities_followup_idx on public.opportunities (follow_up_at) where follow_up_at is not null;
create index if not exists opportunities_search_idx on public.opportunities using gin (search);
create index if not exists opportunities_fp_idx on public.opportunities (fingerprint);
create index if not exists opportunities_title_trgm on public.opportunities using gin (title extensions.gin_trgm_ops);

create table if not exists public.evidence (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid not null references public.opportunities (id) on delete cascade,
  kind           text not null check (kind in ('source_fact', 'reviewer_note', 'verification')),
  source_key     text,
  url            text check (url is null or url ~ '^https://'),
  excerpt        text,
  captured_at    timestamptz not null default now(),
  verification   text,
  rights_note    text,
  created_by     uuid references auth.users (id) on delete set null
);
create index if not exists evidence_opp_idx on public.evidence (opportunity_id);

-- Classification history: every engine run and every human override is a NEW row; nothing is overwritten.
create table if not exists public.classifications (
  id                uuid primary key default gen_random_uuid(),
  opportunity_id    uuid not null references public.opportunities (id) on delete cascade,
  engine            text not null check (engine in ('rules', 'llm', 'human')),
  engine_version    text,
  is_current        boolean not null default true,
  pipeline          text not null,
  pipeline_reason   text,
  priority          text,
  dimensions        jsonb not null default '{}'::jsonb,   -- value + evidence + confidence per dimension (AI/rule interpretation)
  noise_flags       text[] not null default '{}',
  positive_evidence text[] not null default '{}',
  negative_evidence text[] not null default '{}',
  missing_facts     text[] not null default '{}',
  suggested_service text,
  rank_score        integer,
  confidence        text,
  reason            text,                                -- required for human overrides
  cost_usd          numeric(10, 5) not null default 0,
  created_by        uuid references auth.users (id) on delete set null,
  created_at        timestamptz not null default now(),
  constraint human_override_needs_reason check (engine <> 'human' or coalesce(char_length(reason), 0) >= 3)
);
create index if not exists classifications_opp_idx on public.classifications (opportunity_id, created_at desc);
create unique index if not exists classifications_one_current on public.classifications (opportunity_id) where is_current;

create table if not exists public.contact_channels (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid references public.opportunities (id) on delete cascade,
  company_id     uuid references public.companies (id) on delete cascade,
  kind           text not null check (kind in ('in_platform', 'reply_in_thread', 'procurement_portal', 'company_website',
                   'company_contact_form', 'business_email', 'business_phone', 'company_profile')),
  value          text check (char_length(value) <= 300),
  permission     text not null default 'unknown' check (permission in ('invited', 'platform_rules', 'published_for_business', 'unknown', 'do_not_contact')),
  verified       boolean not null default false,
  note           text,
  created_by     uuid references auth.users (id) on delete set null,
  created_at     timestamptz not null default now(),
  check (opportunity_id is not null or company_id is not null)
);
comment on table public.contact_channels is 'Professional contact routes only. No personal e-mails/phones of private individuals.';

-- ----------------------------------------------------------------------------- intake
create table if not exists public.intake_submissions (
  id            uuid primary key default gen_random_uuid(),
  origin        text not null check (origin in ('manual', 'paste', 'email_file', 'csv', 'json', 'inbound_email')),
  source_key    text,
  filename      text check (char_length(filename) <= 200),
  status        text not null check (status in ('processed', 'partial', 'rejected', 'failed')),
  items_found   integer not null default 0,
  items_added   integer not null default 0,
  duplicates    integer not null default 0,
  errors        jsonb not null default '[]'::jsonb,
  unrecognised  boolean not null default false,
  created_by    uuid references auth.users (id) on delete set null,
  created_at    timestamptz not null default now()
);
comment on table public.intake_submissions is 'Intake log. Raw uploaded files are NOT stored; only the parsed, redacted records and these counts.';

create table if not exists public.marketplace_alerts (
  id             uuid primary key default gen_random_uuid(),
  intake_id      uuid references public.intake_submissions (id) on delete cascade,
  platform       text not null,
  received_at    timestamptz not null default now(),
  projects_found integer not null default 0,
  unrecognised   boolean not null default false
);

create table if not exists public.duplicate_links (
  opportunity_id uuid not null references public.opportunities (id) on delete cascade,
  duplicate_of   uuid not null references public.opportunities (id) on delete cascade,
  reason         text not null check (reason in ('same_url', 'same_content', 'similar_title', 'manual')),
  score          real,
  created_at     timestamptz not null default now(),
  primary key (opportunity_id, duplicate_of),
  check (opportunity_id <> duplicate_of)
);

-- ----------------------------------------------------------------------------- sales
create table if not exists public.notes (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid not null references public.opportunities (id) on delete cascade,
  author_id      uuid references auth.users (id) on delete set null default auth.uid(),
  body           text not null check (char_length(body) between 1 and 5000),
  created_at     timestamptz not null default now()
);
create index if not exists notes_opp_idx on public.notes (opportunity_id, created_at desc);

create table if not exists public.activities (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid not null references public.opportunities (id) on delete cascade,
  kind           text not null check (kind in ('stage_change', 'assignment', 'classification_change', 'verification', 'contact',
                   'reply', 'meeting', 'proposal', 'note', 'follow_up', 'won', 'lost', 'created', 'ingested', 'other')),
  summary        text check (char_length(summary) <= 500),
  detail         jsonb not null default '{}'::jsonb,
  actor_id       uuid references auth.users (id) on delete set null default auth.uid(),
  occurred_at    timestamptz not null default now()
);
create index if not exists activities_opp_idx on public.activities (opportunity_id, occurred_at desc);

create table if not exists public.follow_ups (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid not null references public.opportunities (id) on delete cascade,
  title          text not null check (char_length(title) between 1 and 200),
  due_at         timestamptz not null,
  assignee_id    uuid references auth.users (id) on delete set null,
  done_at        timestamptz,
  created_by     uuid references auth.users (id) on delete set null default auth.uid(),
  created_at     timestamptz not null default now()
);
create index if not exists follow_ups_due_idx on public.follow_ups (due_at) where done_at is null;

create table if not exists public.proposals (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid not null references public.opportunities (id) on delete cascade,
  title          text not null check (char_length(title) between 1 and 200),
  amount         numeric(12, 2) check (amount is null or amount >= 0),
  currency       text check (currency is null or currency ~ '^[A-Z]{3}$'),
  status         text not null default 'draft' check (status in ('draft', 'sent', 'accepted', 'rejected', 'withdrawn')),
  sent_at        timestamptz,
  decided_at     timestamptz,
  notes          text,
  created_by     uuid references auth.users (id) on delete set null default auth.uid(),
  created_at     timestamptz not null default now()
);

create table if not exists public.acquisition_costs (
  id             uuid primary key default gen_random_uuid(),
  source_key     text references public.sources (key) on delete set null,
  opportunity_id uuid references public.opportunities (id) on delete set null,
  amount         numeric(10, 2) not null check (amount >= 0),
  currency       text not null default 'GBP' check (currency ~ '^[A-Z]{3}$'),
  incurred_on    date not null default current_date,
  kind           text not null default 'lead_purchase' check (kind in ('lead_purchase', 'credits', 'subscription', 'api_usage', 'llm_usage', 'other')),
  licence_terms  text,
  description    text,
  created_by     uuid references auth.users (id) on delete set null default auth.uid(),
  created_at     timestamptz not null default now()
);

-- ----------------------------------------------------------------------------- searches, notifications, audit, tokens
create table if not exists public.saved_searches (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete cascade default auth.uid(),
  name         text not null check (char_length(name) between 1 and 80),
  filters      jsonb not null default '{}'::jsonb,
  notify       boolean not null default true,
  last_seen_at timestamptz not null default now(),
  created_at   timestamptz not null default now()
);

create table if not exists public.notifications (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  kind       text not null check (kind in ('follow_up_due', 'saved_search_match', 'source_failing', 'intake_result', 'system')),
  title      text not null,
  body       text,
  link       text check (link is null or link ~ '^/'),
  dedupe_key text,
  created_at timestamptz not null default now(),
  read_at    timestamptz,
  emailed_at timestamptz
);
create unique index if not exists notifications_dedupe_uq on public.notifications (user_id, dedupe_key) where dedupe_key is not null;

create table if not exists public.audit_log (
  id         bigint generated always as identity primary key,
  actor_id   uuid,
  action     text not null,
  table_name text not null,
  record_id  text,
  changes    jsonb,
  at         timestamptz not null default now()
);
create index if not exists audit_log_record_idx on public.audit_log (table_name, record_id, at desc);

create table if not exists public.ingest_tokens (
  id           uuid primary key default gen_random_uuid(),
  name         text not null check (char_length(name) between 2 and 60),
  token_hash   text not null unique,
  scopes       text[] not null default '{discovery}' check (scopes <@ array['discovery', 'inbound_email']::text[]),
  created_by   uuid references auth.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at   timestamptz
);
comment on table public.ingest_tokens is 'Hashes of machine ingest tokens (GitHub Actions discovery, inbound e-mail webhook). Plaintext is shown once and never stored.';
