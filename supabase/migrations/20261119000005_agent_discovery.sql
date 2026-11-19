-- Solvant Signal Engine — agent discovery (scheduled Claude task on the owner's subscription; no paid AI API).
-- Changes, all inside schema `solvant`:
--  1. new verification state 'agent_reviewed' (the discovery agent read the original public page; not human-verified);
--  2. _ingest_item accepts it and records the LLM qualification as engine 'llm';
--  3. ingest_records: token may arrive in the proxy-injected x-signal-token header; 'agent' mode for search-discovered
--     records (prohibited sources still rejected); runs logged with origin 'scheduler';
--  4. public procurement collectors switched off (owner decision 2026-11-19: focus on small-business demand).
-- No data is deleted. Re-runnable.

alter table solvant.opportunities drop constraint if exists opportunities_verification_check;
alter table solvant.opportunities add constraint opportunities_verification_check
  check (verification in ('api_verified', 'reviewer_verified', 'user_submitted', 'licensed_import', 'agent_reviewed', 'search_snippet_only'));

create or replace function solvant._ingest_item(p_item jsonb, p_origin text, p_actor uuid, p_allow_statuses text[])
returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_src solvant.sources%rowtype;
  v_url text := p_item ->> 'url';
  v_canon text := coalesce(p_item ->> 'canonical_url', p_item ->> 'url');
  v_ver text := p_item ->> 'verification';
  v_existing solvant.opportunities%rowtype;
  v_dup uuid;
  v_id uuid;
  v_dims jsonb := coalesce(p_item -> 'dims', '{}'::jsonb);
  v_retention int := coalesce((solvant.setting('retention_days', '365'::jsonb))::text::int, 365);
  v_current solvant.classifications%rowtype;
  v_pipeline text := coalesce(p_item ->> 'pipeline', 'H_RESEARCH_UNVERIFIED');
begin
  -- validation (defence in depth: the Python engine applies the same rules)
  if v_url is null or v_url !~ '^https://' or length(v_url) > 2000 then
    return 'rejected:url';
  end if;
  if coalesce(p_item ->> 'source_key', '') = 'web_search_brave' then
    return 'rejected:brave_output_not_retainable';
  end if;
  if v_ver is null or v_ver not in ('api_verified', 'reviewer_verified', 'user_submitted', 'licensed_import', 'agent_reviewed', 'search_snippet_only') then
    return 'rejected:verification';   -- includes 'fixture': synthetic data never becomes a record
  end if;
  select * into v_src from solvant.sources where key = p_item ->> 'source_key';
  if not found then
    return 'rejected:unknown_source';
  end if;
  if not (v_src.permission_status = any (p_allow_statuses)) then
    return 'rejected:source_permission_' || v_src.permission_status;
  end if;
  if v_pipeline not in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER', 'D_OPERATIONAL_PAIN', 'E_PROCUREMENT',
                        'F_RECRUITMENT_SIGNAL', 'G_LICENSED_LEADS', 'H_RESEARCH_UNVERIFIED', 'GLOBAL_REVIEW', 'EXCLUDED') then
    v_pipeline := 'H_RESEARCH_UNVERIFIED';
  end if;

  select * into v_existing from solvant.opportunities where canonical_url = v_canon;
  if found then
    update solvant.opportunities
       set last_seen_at = now(),
           source_state = coalesce(p_item ->> 'source_state', source_state),
           published_at = coalesce(published_at, (p_item ->> 'published_at')::timestamptz)
     where id = v_existing.id;
    select * into v_current from solvant.classifications where opportunity_id = v_existing.id and is_current;
    -- re-classify only when the engine's view changed AND no human override is in force
    if found and v_current.engine <> 'human'
       and (v_current.pipeline is distinct from v_pipeline or v_current.dimensions is distinct from v_dims) then
      update solvant.classifications set is_current = false where id = v_current.id;
      insert into solvant.classifications (opportunity_id, engine, engine_version, pipeline, pipeline_reason, priority, dimensions,
             noise_flags, positive_evidence, negative_evidence, missing_facts, suggested_service, rank_score, confidence)
      values (v_existing.id, case when p_item ->> 'engine' = 'llm' then 'llm' else 'rules' end, p_item ->> 'engine_version', v_pipeline, p_item ->> 'pipeline_reason', p_item ->> 'priority', v_dims,
              coalesce(array(select jsonb_array_elements_text(p_item -> 'noise_flags')), '{}'),
              coalesce(array(select jsonb_array_elements_text(p_item -> 'positive_evidence')), '{}'),
              coalesce(array(select jsonb_array_elements_text(p_item -> 'negative_evidence')), '{}'),
              coalesce(array(select jsonb_array_elements_text(p_item -> 'missing_facts')), '{}'),
              p_item ->> 'suggested_service', (p_item ->> 'rank_score')::int, v_dims #>> '{evidence_confidence,value}');
      update solvant.opportunities
         set pipeline = v_pipeline, pipeline_reason = p_item ->> 'pipeline_reason', priority = p_item ->> 'priority',
             rank_score = coalesce((p_item ->> 'rank_score')::int, 0), suggested_service = p_item ->> 'suggested_service',
             buying_intent = v_dims #>> '{buying_intent,value}', technical_relevance = v_dims #>> '{technical_relevance,value}',
             engagement_type = v_dims #>> '{engagement_type,value}', business_type = v_dims #>> '{business_type,value}',
             decision_maker_access = v_dims #>> '{decision_maker_access,value}', freshness = v_dims #>> '{freshness,value}',
             contact_permission = v_dims #>> '{contact_permission,value}', delivery_complexity = v_dims #>> '{delivery_complexity,value}',
             commercial_potential = v_dims #>> '{commercial_potential,value}', evidence_confidence = v_dims #>> '{evidence_confidence,value}'
       where id = v_existing.id;
    end if;
    return 'updated';
  end if;

  if coalesce(p_item ->> 'fingerprint', '') <> '' and length(coalesce(p_item ->> 'body_excerpt', '')) > 40 then
    select id into v_dup from solvant.opportunities where fingerprint = p_item ->> 'fingerprint' order by discovered_at limit 1;
  end if;

  insert into solvant.opportunities (canonical_url, fingerprint, source_key, source_id, url, title, requirement_summary, body_excerpt,
         published_at, source_state, country, location, org_type, organisation, technologies, budget_text, verification,
         buying_intent, technical_relevance, engagement_type, business_type, decision_maker_access, freshness, contact_permission,
         contact_route, delivery_complexity, commercial_potential, evidence_confidence, priority, pipeline, pipeline_reason,
         rank_score, suggested_service, stage, duplicate_of, acquisition_cost, query_id, discovered_via, origin, retain_until, meta, created_by)
  values (v_canon, p_item ->> 'fingerprint', v_src.key, left(p_item ->> 'source_id', 500), v_url, left(coalesce(p_item ->> 'title', ''), 500),
          left(p_item ->> 'requirement_summary', 2000), left(p_item ->> 'body_excerpt', 4000), (p_item ->> 'published_at')::timestamptz,
          p_item ->> 'source_state', left(p_item ->> 'country', 80), left(p_item ->> 'location', 80), left(p_item ->> 'org_type', 80),
          left(p_item ->> 'organisation', 200), coalesce(array(select jsonb_array_elements_text(p_item -> 'technologies')), '{}'),
          left(p_item ->> 'budget_text', 120), v_ver,
          v_dims #>> '{buying_intent,value}', v_dims #>> '{technical_relevance,value}', v_dims #>> '{engagement_type,value}',
          v_dims #>> '{business_type,value}', v_dims #>> '{decision_maker_access,value}', v_dims #>> '{freshness,value}',
          v_dims #>> '{contact_permission,value}', left(p_item ->> 'contact_route', 200), v_dims #>> '{delivery_complexity,value}',
          v_dims #>> '{commercial_potential,value}', v_dims #>> '{evidence_confidence,value}', p_item ->> 'priority', v_pipeline,
          left(p_item ->> 'pipeline_reason', 500), coalesce((p_item ->> 'rank_score')::int, 0), left(p_item ->> 'suggested_service', 200),
          case when v_pipeline = 'EXCLUDED' then 'archived'::solvant.sales_stage
               when v_dup is not null then 'archived'::solvant.sales_stage
               else 'needs_review'::solvant.sales_stage end,
          v_dup, (p_item ->> 'acquisition_cost')::numeric, left(p_item ->> 'query_id', 120), left(p_item ->> 'discovered_via', 40),
          p_origin, now() + make_interval(days => v_retention), coalesce(p_item -> 'meta', '{}'::jsonb), p_actor)
  returning id into v_id;

  insert into solvant.evidence (opportunity_id, kind, source_key, url, excerpt, verification, rights_note, created_by)
  values (v_id, 'source_fact', v_src.key, v_url, left(p_item ->> 'body_excerpt', 4000), v_ver, p_item ->> 'rights_note', p_actor);

  insert into solvant.classifications (opportunity_id, engine, engine_version, pipeline, pipeline_reason, priority, dimensions, noise_flags,
         positive_evidence, negative_evidence, missing_facts, suggested_service, rank_score, confidence, created_by)
  values (v_id, case when p_item ->> 'engine' = 'llm' then 'llm' else 'rules' end, p_item ->> 'engine_version', v_pipeline, p_item ->> 'pipeline_reason', p_item ->> 'priority', v_dims,
          coalesce(array(select jsonb_array_elements_text(p_item -> 'noise_flags')), '{}'),
          coalesce(array(select jsonb_array_elements_text(p_item -> 'positive_evidence')), '{}'),
          coalesce(array(select jsonb_array_elements_text(p_item -> 'negative_evidence')), '{}'),
          coalesce(array(select jsonb_array_elements_text(p_item -> 'missing_facts')), '{}'),
          p_item ->> 'suggested_service', (p_item ->> 'rank_score')::int, v_dims #>> '{evidence_confidence,value}', p_actor);

  insert into solvant.activities (opportunity_id, kind, summary, detail, actor_id)
  values (v_id, 'ingested', 'Added from ' || p_origin, jsonb_build_object('source', v_src.key, 'verification', v_ver), p_actor);

  if v_dup is not null then
    insert into solvant.duplicate_links (opportunity_id, duplicate_of, reason) values (v_id, v_dup, 'same_content') on conflict do nothing;
    return 'duplicate';
  end if;
  return 'added';
end $$;

create or replace function solvant.ingest_records(p_token text, p_run jsonb, p_items jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_token text;
  v_tok solvant.ingest_tokens%rowtype;
  v_scope text := coalesce(p_run ->> 'scope', 'discovery');
  v_results text[] := '{}';
  v_item jsonb;
  v_log jsonb;
  v_intake uuid;
  v_origin text;
  v_allowed text[];
begin
  -- token as an argument, or (scheduled Claude task) injected by the session's network proxy as the x-signal-token header
  v_token := coalesce(nullif(p_token, ''), nullif(current_setting('request.headers', true), '')::json ->> 'x-signal-token');
  if v_token is null or length(v_token) < 32 then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  select * into v_tok from solvant.ingest_tokens
   where token_hash = encode(sha256(convert_to(v_token, 'UTF8')), 'hex') and revoked_at is null;
  if not found or not (v_scope = any (v_tok.scopes)) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  if jsonb_typeof(coalesce(p_items, '[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_items, '[]'::jsonb)) > 2000 then
    raise exception 'items must be an array of at most 2000 records' using errcode = '22023';
  end if;
  update solvant.ingest_tokens set last_used_at = now() where id = v_tok.id;

  if v_scope = 'discovery' then
    v_origin := 'discovery';
    if p_run ->> 'mode' = 'agent' then
      -- scheduled Claude discovery: records are pointers + short evidence found through search results (platform pages of
      -- manual-only/no-API sources are never fetched); prohibited sources stay rejected
      v_allowed := array['permitted', 'restricted', 'manual_only', 'unknown', 'licensed'];
    else
      v_allowed := array['permitted', 'restricted'];   -- restricted only reaches here after explicit per-run opt-in in the collector
    end if;
    for v_log in select * from jsonb_array_elements(coalesce(p_run -> 'logs', '[]'::jsonb)) loop
      if exists (select 1 from solvant.sources where key = v_log ->> 'source_key') then
        insert into solvant.discovery_runs (source_key, origin, external_run_id, started_at, finished_at, status, requests, records,
               failed_requests, est_cost_usd, error_kind, detail)
        values (v_log ->> 'source_key', case when p_run ->> 'mode' = 'agent' then 'scheduler' else 'github_actions' end, left(p_run ->> 'external_run_id', 80),
                coalesce((p_run ->> 'started_at')::timestamptz, now()), now(),
                case when v_log ->> 'status' in ('ok', 'partial', 'failed', 'skipped') then v_log ->> 'status' else 'ok' end,
                coalesce((v_log ->> 'requests')::int, 0), coalesce((v_log ->> 'records')::int, 0), coalesce((v_log ->> 'failed')::int, 0),
                coalesce((v_log ->> 'est_cost_usd')::numeric, 0), left(v_log ->> 'error_kind', 80),
                coalesce(v_log -> 'counts', '{}'::jsonb));
        update solvant.sources
           set last_run_at = now(), last_status = v_log ->> 'status',
               last_success_at = case when v_log ->> 'status' in ('ok', 'partial') then now() else last_success_at end,
               last_error = case when v_log ->> 'status' in ('failed', 'partial') then left(coalesce(v_log ->> 'error_kind', 'error'), 300)
                                 when v_log ->> 'status' = 'ok' then null else last_error end
         where key = v_log ->> 'source_key';
      end if;
    end loop;
  else
    v_origin := 'inbound_email';
    v_allowed := array['permitted', 'restricted', 'manual_only', 'licensed', 'unknown'];
    insert into solvant.intake_submissions (origin, source_key, status, items_found, unrecognised)
    values ('inbound_email', left(p_run ->> 'source_key', 80), 'processed', jsonb_array_length(coalesce(p_items, '[]'::jsonb)),
            coalesce((p_run ->> 'unrecognised')::boolean, false))
    returning id into v_intake;
    insert into solvant.marketplace_alerts (intake_id, platform, projects_found, unrecognised)
    values (v_intake, coalesce(p_run ->> 'source_key', 'unknown'), jsonb_array_length(coalesce(p_items, '[]'::jsonb)),
            coalesce((p_run ->> 'unrecognised')::boolean, false));
  end if;

  for v_item in select * from jsonb_array_elements(coalesce(p_items, '[]'::jsonb)) loop
    v_results := v_results || solvant._ingest_item(v_item, v_origin, null, v_allowed);
  end loop;

  if v_intake is not null then
    update solvant.intake_submissions set items_added = (solvant._tally(v_results) ->> 'added')::int,
           duplicates = (solvant._tally(v_results) ->> 'duplicates')::int where id = v_intake;
  end if;
  return solvant._tally(v_results);
end $$;

revoke all on function solvant._ingest_item(jsonb, text, uuid, text[]) from public, anon, authenticated;
revoke all on function solvant.ingest_records(text, jsonb, jsonb) from public;
grant execute on function solvant.ingest_records(text, jsonb, jsonb) to anon, authenticated;

update solvant.sources set enabled = false, schedule_cron = null
 where key in ('contracts_finder', 'find_a_tender', 'ted') and enabled;

insert into solvant.schema_migrations (version) values ('20261119000005') on conflict do nothing;
