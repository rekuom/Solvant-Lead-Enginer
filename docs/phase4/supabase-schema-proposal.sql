-- Solvant Signal Engine — PROPOSED schema for the dedicated Solvant Supabase project (ref dfnaevcsergsphiiodtm).
-- STATUS: PROPOSAL ONLY. Not applied. Requires explicit approval. Never apply to Rekuo / jobplatform / PlumRole projects.
-- Principles: evidence ≠ interpretation ≠ sales activity; provenance on every row; retention + deletion; RLS everywhere.

create schema if not exists signal;

-- ---------------------------------------------------------------- sources & policy
create table signal.sources (
  key text primary key,                       -- registry key, e.g. 'github_issues'
  name text not null,
  family text not null,
  created_at timestamptz not null default now()
);
create table signal.source_policies (           -- versioned: a new row per review
  id bigint generated always as identity primary key,
  source_key text not null references signal.sources(key),
  status text not null check (status in ('permitted','restricted','manual_only','licensed','unknown','prohibited')),
  collection text not null, auth text, rate_limit text, cost text, commercial_reuse text,
  contact_route text, marketplace_rules jsonb, evidence_urls text[] not null default '{}',
  review_date date not null, reviewed_by uuid, notes text,
  valid_from timestamptz not null default now(), valid_to timestamptz
);

-- ---------------------------------------------------------------- queries & runs
create table signal.search_queries (
  id text primary key,                         -- e.g. 'github:explic-en-00'
  provider text not null, category text not null, lang text not null, text text not null,
  translation_confidence text not null, active boolean not null default true
);
create table signal.collection_runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default now(), finished_at timestamptz,
  trigger text not null,                        -- 'workflow_dispatch' / 'manual'
  dry_run boolean not null default false, allow_restricted text[] not null default '{}',
  status text not null,                         -- ok / partial / failed
  stage_audit jsonb, est_cost_usd numeric(10,4) default 0, actual_cost_usd numeric(10,4)
);
create table signal.connector_logs (
  id bigint generated always as identity primary key,
  run_id uuid not null references signal.collection_runs(id) on delete cascade,
  source_key text not null references signal.sources(key),
  query_id text references signal.search_queries(id),
  status text not null, http_status int, error_kind text, returned int, at timestamptz not null default now()
);

-- ---------------------------------------------------------------- evidence (raw, minimal)
create table signal.evidence_records (
  id uuid primary key default gen_random_uuid(),
  source_key text not null references signal.sources(key),
  source_id text not null,
  url text not null check (url like 'https://%'),
  title text not null,
  excerpt text not null,                        -- PII-redacted, length-capped
  verification text not null check (verification in ('api_verified','reviewer_verified','user_submitted','licensed_import','search_snippet_only')),
  source_created_at timestamptz, source_updated_at timestamptz, source_state text,
  fetched_at timestamptz not null default now(), run_id uuid references signal.collection_runs(id),
  query_id text, language text, author_ref text,  -- salted hash only; never the handle
  meta jsonb not null default '{}',
  retain_until date not null default (now() + interval '180 days')::date,
  deleted_at timestamptz,                       -- set on source deletion / objection; excerpt purged
  unique (source_key, source_id)
);

-- ---------------------------------------------------------------- companies & lawful professional contacts
create table signal.companies (
  id uuid primary key default gen_random_uuid(),
  name text not null, website text, country text, sector text,
  employee_range text, employee_range_basis text check (employee_range_basis in ('registry','company_website','self_reported','estimated')),
  ownership text check (ownership in ('independent','private_group','public_company','public_sector','unknown')),
  founder_led text check (founder_led in ('confirmed','self_reported','unknown')),
  registry_id text, registry_source text, enriched_at timestamptz
);
create table signal.contacts (                   -- only lawfully obtained professional contact routes
  id uuid primary key default gen_random_uuid(),
  company_id uuid references signal.companies(id),
  role_title text, channel text not null,       -- 'platform_message', 'procurement_portal', 'business_enquiry_form', 'stated_in_post'
  channel_value text,                           -- never a guessed e-mail
  lawful_basis text not null, source_evidence_id uuid references signal.evidence_records(id),
  suppressed boolean not null default false, created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- opportunities & assessments
create table signal.opportunities (
  id uuid primary key default gen_random_uuid(),
  evidence_id uuid not null references signal.evidence_records(id),
  company_id uuid references signal.companies(id),
  pipeline text not null check (pipeline in ('A_DIRECT_SME','B_FREELANCE_PROJECT','C_AGENCY_PARTNER','D_OPERATIONAL_PAIN','E_PROCUREMENT',
                                             'F_RECRUITMENT_SIGNAL','G_LICENSED_LEADS','H_RESEARCH_UNVERIFIED','GLOBAL_REVIEW','EXCLUDED')),
  pipeline_reason text not null, rank_score int not null default 0, rank_explanation text[] not null default '{}',
  suggested_service text, next_action text,
  stage text not null default 'new' check (stage in ('new','verified','assigned','contacted','replied','qualified','proposal_sent','won','lost','rejected')),
  owner_id uuid, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table signal.assessments (                -- one row per classifier version (history kept)
  id bigint generated always as identity primary key,
  opportunity_id uuid not null references signal.opportunities(id) on delete cascade,
  classifier_version text not null, dimensions jsonb not null,   -- A–J with value/evidence/confidence
  noise_flags text[] not null default '{}', missing_facts text[] not null default '{}',
  created_at timestamptz not null default now()
);
create table signal.project_requirements (
  opportunity_id uuid primary key references signal.opportunities(id) on delete cascade,
  summary text, systems text[], budget_stated text, budget_currency text, deadline date,
  complexity text, delivery_flags text[]
);
create table signal.duplicates (
  opportunity_id uuid references signal.opportunities(id) on delete cascade,
  duplicate_of uuid references signal.opportunities(id), reason text not null,
  primary key (opportunity_id, duplicate_of)
);

-- ---------------------------------------------------------------- review, outreach permission, sales
create table signal.reviews (
  id bigint generated always as identity primary key,
  opportunity_id uuid not null references signal.opportunities(id) on delete cascade,
  reviewer_id uuid not null, blind boolean not null default true,
  labels jsonb not null,                        -- genuine/relevant/intent/business/engagement/contact_ok
  corrected_pipeline text, notes text, created_at timestamptz not null default now()
);
create table signal.outreach_permissions (
  opportunity_id uuid primary key references signal.opportunities(id) on delete cascade,
  route text not null, allowed boolean not null, basis text not null, checked_by uuid, checked_at timestamptz
);
create table signal.acquisition_costs (          -- marketplace credits, subscriptions, ads
  id bigint generated always as identity primary key,
  opportunity_id uuid references signal.opportunities(id), source_key text references signal.sources(key),
  amount numeric(12,2) not null, currency text not null, kind text not null, exclusivity text, notes text, at timestamptz not null default now()
);
create table signal.sales_activities (
  id bigint generated always as identity primary key,
  opportunity_id uuid not null references signal.opportunities(id) on delete cascade,
  kind text not null check (kind in ('contacted','replied','call','proposal_sent','won','lost','follow_up')),
  value_amount numeric(12,2), value_currency text, notes text, actor_id uuid, at timestamptz not null default now()
);
create table signal.suppression (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('author_ref','domain','url','company')), value text not null, reason text not null,
  created_at timestamptz not null default now(), unique (kind, value)
);

-- ---------------------------------------------------------------- source performance (view)
create view signal.source_performance as
select e.source_key,
       count(*) as opportunities,
       count(*) filter (where e.verification in ('api_verified','reviewer_verified')) as verified,
       count(*) filter (where o.pipeline in ('A_DIRECT_SME','B_FREELANCE_PROJECT','C_AGENCY_PARTNER')) as actionable,
       count(distinct s.opportunity_id) filter (where s.kind = 'replied') as conversations,
       count(distinct s.opportunity_id) filter (where s.kind = 'proposal_sent') as proposals,
       count(distinct s.opportunity_id) filter (where s.kind = 'won') as wins,
       coalesce(sum(s.value_amount) filter (where s.kind = 'won'), 0) as revenue,
       coalesce((select sum(c.amount) from signal.acquisition_costs c where c.source_key = e.source_key), 0) as acquisition_cost
from signal.opportunities o
join signal.evidence_records e on e.id = o.evidence_id
left join signal.sales_activities s on s.opportunity_id = o.id
group by e.source_key;

-- ---------------------------------------------------------------- RLS (sketch)
alter table signal.evidence_records enable row level security;
alter table signal.opportunities enable row level security;
alter table signal.contacts enable row level security;
alter table signal.reviews enable row level security;
alter table signal.sales_activities enable row level security;
-- Policies (to be finalised): authenticated internal users with role 'reviewer' or 'admin' (custom claim) may select;
-- writes to evidence/assessments only via service role from collectors; contacts readable by 'admin' + assigned owner only;
-- suppression enforced at insert (trigger) — no anon access to any table in schema signal.
