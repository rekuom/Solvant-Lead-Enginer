-- Solvant Signal Engine — functions, triggers and RPCs (create or replace only; no data changes).
-- Every SECURITY DEFINER function pins search_path = '' and fully qualifies objects.

-- ----------------------------------------------------------------------------- role helpers
create or replace function public.my_role() returns public.app_role
language sql stable security definer set search_path = '' as $$
  select m.role from public.members m where m.user_id = auth.uid()
$$;

create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.members m where m.user_id = auth.uid())
$$;

create or replace function public.can_edit() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.members m where m.user_id = auth.uid() and m.role in ('admin', 'editor'))
$$;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.members m where m.user_id = auth.uid() and m.role = 'admin')
$$;

create or replace function public.setting(p_key text, p_default jsonb) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce((select s.value from public.app_settings s where s.key = p_key), p_default)
$$;

-- ----------------------------------------------------------------------------- generic triggers
create or replace function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

create or replace function public.audit_row() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_old jsonb := case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) end;
  v_new jsonb := case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) end;
  v_changes jsonb;
begin
  if tg_op = 'UPDATE' then
    select coalesce(jsonb_object_agg(k, jsonb_build_object('old', v_old -> k, 'new', v_new -> k)), '{}'::jsonb)
      into v_changes
      from jsonb_object_keys(v_new) k
     where k not in ('updated_at', 'search', 'last_seen_at', 'body_excerpt', 'requirement_summary')
       and (v_old -> k) is distinct from (v_new -> k);
    if v_changes = '{}'::jsonb then
      return new;
    end if;
  elsif tg_op = 'INSERT' then
    v_changes := jsonb_build_object('created', true);
  else
    v_changes := jsonb_build_object('deleted', true);
  end if;
  insert into public.audit_log (actor_id, action, table_name, record_id, changes)
  values (auth.uid(), lower(tg_op), tg_table_name, coalesce(v_new ->> 'id', v_old ->> 'id', v_new ->> 'key', v_old ->> 'key',
          v_new ->> 'user_id', v_old ->> 'user_id'), v_changes);
  return coalesce(new, old);
end $$;

-- Sales activity log for opportunity changes (stage, owner, follow-up, won/lost).
create or replace function public.opportunity_activity() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.stage is distinct from old.stage then
    if new.stage = 'won' and new.won_at is null then
      new.won_at := now();
    end if;
    insert into public.activities (opportunity_id, kind, summary, detail, actor_id)
    values (new.id, case new.stage when 'won' then 'won' when 'lost' then 'lost' else 'stage_change' end,
            'Stage: ' || old.stage || ' → ' || new.stage,
            jsonb_build_object('from', old.stage, 'to', new.stage, 'lost_reason', new.lost_reason, 'win_reason', new.win_reason), auth.uid());
  end if;
  if new.owner_id is distinct from old.owner_id then
    insert into public.activities (opportunity_id, kind, summary, detail, actor_id)
    values (new.id, 'assignment', 'Owner changed', jsonb_build_object('from', old.owner_id, 'to', new.owner_id), auth.uid());
  end if;
  if new.follow_up_at is distinct from old.follow_up_at then
    insert into public.activities (opportunity_id, kind, summary, detail, actor_id)
    values (new.id, 'follow_up', 'Follow-up date set', jsonb_build_object('from', old.follow_up_at, 'to', new.follow_up_at), auth.uid());
  end if;
  return new;
end $$;

-- ----------------------------------------------------------------------------- ingestion core (not callable via the API)
create or replace function public._ingest_item(p_item jsonb, p_origin text, p_actor uuid, p_allow_statuses text[])
returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_src public.sources%rowtype;
  v_url text := p_item ->> 'url';
  v_canon text := coalesce(p_item ->> 'canonical_url', p_item ->> 'url');
  v_ver text := p_item ->> 'verification';
  v_existing public.opportunities%rowtype;
  v_dup uuid;
  v_id uuid;
  v_dims jsonb := coalesce(p_item -> 'dims', '{}'::jsonb);
  v_retention int := coalesce((public.setting('retention_days', '365'::jsonb))::text::int, 365);
  v_current public.classifications%rowtype;
  v_pipeline text := coalesce(p_item ->> 'pipeline', 'H_RESEARCH_UNVERIFIED');
begin
  -- validation (defence in depth: the Python engine applies the same rules)
  if v_url is null or v_url !~ '^https://' or length(v_url) > 2000 then
    return 'rejected:url';
  end if;
  if coalesce(p_item ->> 'source_key', '') = 'web_search_brave' then
    return 'rejected:brave_output_not_retainable';
  end if;
  if v_ver is null or v_ver not in ('api_verified', 'reviewer_verified', 'user_submitted', 'licensed_import', 'search_snippet_only') then
    return 'rejected:verification';   -- includes 'fixture': synthetic data never becomes a record
  end if;
  select * into v_src from public.sources where key = p_item ->> 'source_key';
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

  select * into v_existing from public.opportunities where canonical_url = v_canon;
  if found then
    update public.opportunities
       set last_seen_at = now(),
           source_state = coalesce(p_item ->> 'source_state', source_state),
           published_at = coalesce(published_at, (p_item ->> 'published_at')::timestamptz)
     where id = v_existing.id;
    select * into v_current from public.classifications where opportunity_id = v_existing.id and is_current;
    -- re-classify only when the engine's view changed AND no human override is in force
    if found and v_current.engine <> 'human'
       and (v_current.pipeline is distinct from v_pipeline or v_current.dimensions is distinct from v_dims) then
      update public.classifications set is_current = false where id = v_current.id;
      insert into public.classifications (opportunity_id, engine, engine_version, pipeline, pipeline_reason, priority, dimensions,
             noise_flags, positive_evidence, negative_evidence, missing_facts, suggested_service, rank_score, confidence)
      values (v_existing.id, 'rules', p_item ->> 'engine_version', v_pipeline, p_item ->> 'pipeline_reason', p_item ->> 'priority', v_dims,
              coalesce(array(select jsonb_array_elements_text(p_item -> 'noise_flags')), '{}'),
              coalesce(array(select jsonb_array_elements_text(p_item -> 'positive_evidence')), '{}'),
              coalesce(array(select jsonb_array_elements_text(p_item -> 'negative_evidence')), '{}'),
              coalesce(array(select jsonb_array_elements_text(p_item -> 'missing_facts')), '{}'),
              p_item ->> 'suggested_service', (p_item ->> 'rank_score')::int, v_dims #>> '{evidence_confidence,value}');
      update public.opportunities
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
    select id into v_dup from public.opportunities where fingerprint = p_item ->> 'fingerprint' order by discovered_at limit 1;
  end if;

  insert into public.opportunities (canonical_url, fingerprint, source_key, source_id, url, title, requirement_summary, body_excerpt,
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
          case when v_pipeline = 'EXCLUDED' then 'archived'::public.sales_stage
               when v_dup is not null then 'archived'::public.sales_stage
               else 'needs_review'::public.sales_stage end,
          v_dup, (p_item ->> 'acquisition_cost')::numeric, left(p_item ->> 'query_id', 120), left(p_item ->> 'discovered_via', 40),
          p_origin, now() + make_interval(days => v_retention), coalesce(p_item -> 'meta', '{}'::jsonb), p_actor)
  returning id into v_id;

  insert into public.evidence (opportunity_id, kind, source_key, url, excerpt, verification, rights_note, created_by)
  values (v_id, 'source_fact', v_src.key, v_url, left(p_item ->> 'body_excerpt', 4000), v_ver, p_item ->> 'rights_note', p_actor);

  insert into public.classifications (opportunity_id, engine, engine_version, pipeline, pipeline_reason, priority, dimensions, noise_flags,
         positive_evidence, negative_evidence, missing_facts, suggested_service, rank_score, confidence, created_by)
  values (v_id, 'rules', p_item ->> 'engine_version', v_pipeline, p_item ->> 'pipeline_reason', p_item ->> 'priority', v_dims,
          coalesce(array(select jsonb_array_elements_text(p_item -> 'noise_flags')), '{}'),
          coalesce(array(select jsonb_array_elements_text(p_item -> 'positive_evidence')), '{}'),
          coalesce(array(select jsonb_array_elements_text(p_item -> 'negative_evidence')), '{}'),
          coalesce(array(select jsonb_array_elements_text(p_item -> 'missing_facts')), '{}'),
          p_item ->> 'suggested_service', (p_item ->> 'rank_score')::int, v_dims #>> '{evidence_confidence,value}', p_actor);

  insert into public.activities (opportunity_id, kind, summary, detail, actor_id)
  values (v_id, 'ingested', 'Added from ' || p_origin, jsonb_build_object('source', v_src.key, 'verification', v_ver), p_actor);

  if v_dup is not null then
    insert into public.duplicate_links (opportunity_id, duplicate_of, reason) values (v_id, v_dup, 'same_content') on conflict do nothing;
    return 'duplicate';
  end if;
  return 'added';
end $$;

create or replace function public._tally(p_results text[]) returns jsonb
language sql immutable set search_path = '' as $$
  select jsonb_build_object(
    'added', count(*) filter (where r = 'added'),
    'updated', count(*) filter (where r = 'updated'),
    'duplicates', count(*) filter (where r = 'duplicate'),
    'rejected', count(*) filter (where r like 'rejected:%'),
    'rejected_reasons', coalesce((select jsonb_object_agg(x, n) from (select r2 as x, count(*) as n from unnest(p_results) r2
                                   where r2 like 'rejected:%' group by r2) t), '{}'::jsonb))
  from unnest(p_results) r
$$;

-- ----------------------------------------------------------------------------- machine ingestion (GitHub Actions, inbound e-mail)
create or replace function public.ingest_records(p_token text, p_run jsonb, p_items jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_tok public.ingest_tokens%rowtype;
  v_scope text := coalesce(p_run ->> 'scope', 'discovery');
  v_results text[] := '{}';
  v_item jsonb;
  v_log jsonb;
  v_intake uuid;
  v_origin text;
  v_allowed text[];
begin
  if p_token is null or length(p_token) < 32 then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  select * into v_tok from public.ingest_tokens
   where token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex') and revoked_at is null;
  if not found or not (v_scope = any (v_tok.scopes)) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  if jsonb_typeof(coalesce(p_items, '[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_items, '[]'::jsonb)) > 2000 then
    raise exception 'items must be an array of at most 2000 records' using errcode = '22023';
  end if;
  update public.ingest_tokens set last_used_at = now() where id = v_tok.id;

  if v_scope = 'discovery' then
    v_origin := 'discovery';
    v_allowed := array['permitted', 'restricted'];   -- restricted only reaches here after explicit per-run opt-in in the collector
    for v_log in select * from jsonb_array_elements(coalesce(p_run -> 'logs', '[]'::jsonb)) loop
      if exists (select 1 from public.sources where key = v_log ->> 'source_key') then
        insert into public.discovery_runs (source_key, origin, external_run_id, started_at, finished_at, status, requests, records,
               failed_requests, est_cost_usd, error_kind, detail)
        values (v_log ->> 'source_key', 'github_actions', left(p_run ->> 'external_run_id', 80),
                coalesce((p_run ->> 'started_at')::timestamptz, now()), now(),
                case when v_log ->> 'status' in ('ok', 'partial', 'failed', 'skipped') then v_log ->> 'status' else 'ok' end,
                coalesce((v_log ->> 'requests')::int, 0), coalesce((v_log ->> 'records')::int, 0), coalesce((v_log ->> 'failed')::int, 0),
                coalesce((v_log ->> 'est_cost_usd')::numeric, 0), left(v_log ->> 'error_kind', 80),
                coalesce(v_log -> 'counts', '{}'::jsonb));
        update public.sources
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
    insert into public.intake_submissions (origin, source_key, status, items_found, unrecognised)
    values ('inbound_email', left(p_run ->> 'source_key', 80), 'processed', jsonb_array_length(coalesce(p_items, '[]'::jsonb)),
            coalesce((p_run ->> 'unrecognised')::boolean, false))
    returning id into v_intake;
    insert into public.marketplace_alerts (intake_id, platform, projects_found, unrecognised)
    values (v_intake, coalesce(p_run ->> 'source_key', 'unknown'), jsonb_array_length(coalesce(p_items, '[]'::jsonb)),
            coalesce((p_run ->> 'unrecognised')::boolean, false));
  end if;

  for v_item in select * from jsonb_array_elements(coalesce(p_items, '[]'::jsonb)) loop
    v_results := v_results || public._ingest_item(v_item, v_origin, null, v_allowed);
  end loop;

  if v_intake is not null then
    update public.intake_submissions set items_added = (public._tally(v_results) ->> 'added')::int,
           duplicates = (public._tally(v_results) ->> 'duplicates')::int where id = v_intake;
  end if;
  return public._tally(v_results);
end $$;

-- ----------------------------------------------------------------------------- browser intake (signed-in editors)
create or replace function public.save_intake(p_intake jsonb, p_items jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_results text[] := '{}';
  v_item jsonb;
  v_intake uuid;
  v_origin text := coalesce(p_intake ->> 'origin', 'manual');
  v_opp_origin text;
  v_tally jsonb;
  v_status text;
begin
  if not public.can_edit() then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  if v_origin not in ('manual', 'paste', 'email_file', 'csv', 'json') then
    raise exception 'bad origin' using errcode = '22023';
  end if;
  if jsonb_typeof(coalesce(p_items, '[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_items, '[]'::jsonb)) > 1000 then
    raise exception 'items must be an array of at most 1000 records' using errcode = '22023';
  end if;
  v_opp_origin := case v_origin when 'csv' then 'csv' when 'json' then 'csv' when 'manual' then 'manual' else 'web_intake' end;
  for v_item in select * from jsonb_array_elements(coalesce(p_items, '[]'::jsonb)) loop
    v_results := v_results || public._ingest_item(v_item, v_opp_origin, auth.uid(),
                                                  array['permitted', 'restricted', 'manual_only', 'licensed', 'unknown']);
  end loop;
  v_tally := public._tally(v_results);
  v_status := case when jsonb_array_length(coalesce(p_items, '[]'::jsonb)) = 0 then 'rejected'
                   when (v_tally ->> 'rejected')::int = 0 then 'processed'
                   when (v_tally ->> 'added')::int + (v_tally ->> 'updated')::int + (v_tally ->> 'duplicates')::int > 0 then 'partial'
                   else 'rejected' end;
  insert into public.intake_submissions (origin, source_key, filename, status, items_found, items_added, duplicates, errors, unrecognised, created_by)
  values (v_origin, left(p_intake ->> 'source_key', 80), left(p_intake ->> 'filename', 200), v_status,
          jsonb_array_length(coalesce(p_items, '[]'::jsonb)), (v_tally ->> 'added')::int, (v_tally ->> 'duplicates')::int,
          coalesce(p_intake -> 'errors', '[]'::jsonb), coalesce((p_intake ->> 'unrecognised')::boolean, false), auth.uid())
  returning id into v_intake;
  if v_origin = 'email_file' then
    insert into public.marketplace_alerts (intake_id, platform, projects_found, unrecognised)
    values (v_intake, coalesce(p_intake ->> 'source_key', 'unknown'), jsonb_array_length(coalesce(p_items, '[]'::jsonb)),
            coalesce((p_intake ->> 'unrecognised')::boolean, false));
  end if;
  return v_tally || jsonb_build_object('intake_id', v_intake, 'results', to_jsonb(v_results),
         'ids', coalesce((select jsonb_agg(o.id) from public.opportunities o
                           where o.canonical_url in (select coalesce(x ->> 'canonical_url', x ->> 'url') from jsonb_array_elements(p_items) x)), '[]'::jsonb));
end $$;

-- ----------------------------------------------------------------------------- review and correction (history preserved)
create or replace function public.override_classification(p_opp uuid, p_pipeline text, p_priority text, p_dims jsonb, p_reason text)
returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_cur public.classifications%rowtype;
  v_dims jsonb;
  v_id uuid;
begin
  if not public.can_edit() then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  if coalesce(char_length(p_reason), 0) < 3 then
    raise exception 'a reason is required' using errcode = '22023';
  end if;
  if p_pipeline not in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER', 'D_OPERATIONAL_PAIN', 'E_PROCUREMENT',
                        'F_RECRUITMENT_SIGNAL', 'G_LICENSED_LEADS', 'H_RESEARCH_UNVERIFIED', 'GLOBAL_REVIEW', 'EXCLUDED') then
    raise exception 'bad pipeline' using errcode = '22023';
  end if;
  if p_priority is not null and p_priority not in ('A', 'B', 'C') then
    raise exception 'bad priority' using errcode = '22023';
  end if;
  select * into v_cur from public.classifications where opportunity_id = p_opp and is_current;
  v_dims := coalesce(v_cur.dimensions, '{}'::jsonb);
  -- human values are recorded with evidence "human override"; untouched dimensions keep the engine's evidence
  select v_dims || coalesce(jsonb_object_agg(k, jsonb_build_object('value', p_dims ->> k, 'evidence', jsonb_build_array('human override: ' || p_reason),
                                                                    'confidence', 'high')), '{}'::jsonb)
    into v_dims from jsonb_object_keys(coalesce(p_dims, '{}'::jsonb)) k;
  update public.classifications set is_current = false where opportunity_id = p_opp and is_current;
  insert into public.classifications (opportunity_id, engine, pipeline, pipeline_reason, priority, dimensions, noise_flags, missing_facts,
         suggested_service, rank_score, confidence, reason, created_by)
  values (p_opp, 'human', p_pipeline, 'Human override: ' || p_reason, p_priority, v_dims, coalesce(v_cur.noise_flags, '{}'),
          coalesce(v_cur.missing_facts, '{}'), v_cur.suggested_service, v_cur.rank_score, 'high', p_reason, auth.uid())
  returning id into v_id;
  update public.opportunities
     set pipeline = p_pipeline, priority = p_priority, pipeline_reason = 'Human override: ' || p_reason,
         buying_intent = coalesce(p_dims ->> 'buying_intent', buying_intent),
         technical_relevance = coalesce(p_dims ->> 'technical_relevance', technical_relevance),
         engagement_type = coalesce(p_dims ->> 'engagement_type', engagement_type),
         business_type = coalesce(p_dims ->> 'business_type', business_type),
         contact_permission = coalesce(p_dims ->> 'contact_permission', contact_permission)
   where id = p_opp;
  if not found then
    raise exception 'opportunity not found' using errcode = 'P0002';
  end if;
  insert into public.activities (opportunity_id, kind, summary, detail)
  values (p_opp, 'classification_change', 'Classification corrected: ' || coalesce(v_cur.pipeline, '?') || ' → ' || p_pipeline,
          jsonb_build_object('from', v_cur.pipeline, 'to', p_pipeline, 'reason', p_reason, 'previous_classification', v_cur.id));
  return v_id;
end $$;

create or replace function public.verify_opportunity(p_opp uuid, p_note text)
returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_edit() then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  if coalesce(char_length(p_note), 0) < 3 then
    raise exception 'describe what you checked on the original page' using errcode = '22023';
  end if;
  update public.opportunities
     set verification = 'reviewer_verified', verified_by = auth.uid(), verified_at = now(),
         stage = case when stage in ('discovered', 'needs_review') then 'verified'::public.sales_stage else stage end
   where id = p_opp;
  if not found then
    raise exception 'opportunity not found' using errcode = 'P0002';
  end if;
  insert into public.evidence (opportunity_id, kind, excerpt, verification, created_by)
  values (p_opp, 'verification', left(p_note, 2000), 'reviewer_verified', auth.uid());
  insert into public.activities (opportunity_id, kind, summary, detail)
  values (p_opp, 'verification', 'Verified against the original source', jsonb_build_object('note', left(p_note, 500)));
end $$;

create or replace function public.mark_duplicate(p_opp uuid, p_of uuid)
returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_edit() then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  insert into public.duplicate_links (opportunity_id, duplicate_of, reason) values (p_opp, p_of, 'manual') on conflict do nothing;
  update public.opportunities set duplicate_of = p_of, stage = 'archived' where id = p_opp;
  insert into public.activities (opportunity_id, kind, summary, detail)
  values (p_opp, 'other', 'Marked as duplicate', jsonb_build_object('duplicate_of', p_of));
end $$;

create or replace function public.possible_duplicates(p_opp uuid)
returns table (id uuid, title text, source_key text, similarity real)
language sql stable security invoker set search_path = '' as $$
  select o2.id, o2.title, o2.source_key, extensions.similarity(o1.title, o2.title)
    from public.opportunities o1
    join public.opportunities o2 on o2.id <> o1.id and extensions.similarity(o1.title, o2.title) > 0.55
   where o1.id = p_opp and length(o1.title) > 10
   order by 4 desc
   limit 10
$$;

-- ----------------------------------------------------------------------------- members and tokens
create or replace function public.claim_admin(p_code text)
returns boolean
language plpgsql security definer set search_path = '' as $$
declare
  v_id uuid;
begin
  if auth.uid() is null then
    raise exception 'sign in first' using errcode = '28000';
  end if;
  select id into v_id from public.admin_bootstrap
   where code_hash = encode(sha256(convert_to(coalesce(p_code, ''), 'UTF8')), 'hex') and used_at is null and expires_at > now()
   for update;
  if not found then
    raise exception 'invalid or expired code' using errcode = '28000';
  end if;
  update public.admin_bootstrap set used_at = now(), used_by = auth.uid() where id = v_id;
  insert into public.members (user_id, role) values (auth.uid(), 'admin')
  on conflict (user_id) do update set role = 'admin';
  return true;
end $$;

-- Run by the project owner/operator in the SQL editor (never exposed to the API). Returns the plaintext code once.
create or replace function public.create_bootstrap_code(p_days int default 7)
returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_code text := replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '');
begin
  insert into public.admin_bootstrap (code_hash, expires_at)
  values (encode(sha256(convert_to(v_code, 'UTF8')), 'hex'), now() + make_interval(days => greatest(1, least(p_days, 30))));
  return v_code;
end $$;

create or replace function public.create_ingest_token(p_name text, p_scopes text[] default array['discovery'])
returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_token text := 'sse_' || replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '');
begin
  if not public.is_admin() then
    raise exception 'admins only' using errcode = '42501';
  end if;
  insert into public.ingest_tokens (name, token_hash, scopes, created_by)
  values (p_name, encode(sha256(convert_to(v_token, 'UTF8')), 'hex'), p_scopes, auth.uid());
  return v_token;
end $$;

create or replace function public.revoke_ingest_token(p_id uuid)
returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_admin() then
    raise exception 'admins only' using errcode = '42501';
  end if;
  update public.ingest_tokens set revoked_at = now() where id = p_id and revoked_at is null;
end $$;

create or replace function public.list_members()
returns table (user_id uuid, email text, role public.app_role, display_name text, created_at timestamptz)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.is_member() then
    raise exception 'members only' using errcode = '42501';
  end if;
  return query
    select m.user_id, case when public.is_admin() or m.user_id = auth.uid() then u.email::text end, m.role, m.display_name, m.created_at
      from public.members m join auth.users u on u.id = m.user_id
     order by m.created_at;
end $$;

create or replace function public.add_member(p_email text, p_role public.app_role)
returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_uid uuid;
begin
  if not public.is_admin() then
    raise exception 'admins only' using errcode = '42501';
  end if;
  select id into v_uid from auth.users where lower(email) = lower(trim(p_email));
  if not found then
    raise exception 'that person must create an account first' using errcode = 'P0002';
  end if;
  insert into public.members (user_id, role) values (v_uid, p_role) on conflict (user_id) do update set role = excluded.role;
  return v_uid;
end $$;

create or replace function public.remove_member(p_user uuid)
returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_admin() then
    raise exception 'admins only' using errcode = '42501';
  end if;
  if p_user = auth.uid() and (select count(*) from public.members where role = 'admin') <= 1 then
    raise exception 'cannot remove the last admin' using errcode = '22023';
  end if;
  delete from public.members where user_id = p_user;
end $$;

-- ----------------------------------------------------------------------------- dashboard, notifications, retention
create or replace function public.dashboard_counts()
returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'today', count(*) filter (where o.discovered_at >= date_trunc('day', now())),
    'week', count(*) filter (where o.discovered_at >= now() - interval '7 days'),
    'month', count(*) filter (where o.discovered_at >= now() - interval '30 days'),
    'all', count(*),
    'verified', count(*) filter (where o.verification in ('api_verified', 'reviewer_verified')),
    'unverified', count(*) filter (where o.verification not in ('api_verified', 'reviewer_verified')),
    'A_DIRECT_SME', count(*) filter (where o.pipeline = 'A_DIRECT_SME'),
    'B_FREELANCE_PROJECT', count(*) filter (where o.pipeline = 'B_FREELANCE_PROJECT'),
    'C_AGENCY_PARTNER', count(*) filter (where o.pipeline = 'C_AGENCY_PARTNER'),
    'D_OPERATIONAL_PAIN', count(*) filter (where o.pipeline = 'D_OPERATIONAL_PAIN'),
    'E_PROCUREMENT', count(*) filter (where o.pipeline = 'E_PROCUREMENT'),
    'F_RECRUITMENT_SIGNAL', count(*) filter (where o.pipeline = 'F_RECRUITMENT_SIGNAL'),
    'G_LICENSED_LEADS', count(*) filter (where o.pipeline = 'G_LICENSED_LEADS'),
    'H_RESEARCH_UNVERIFIED', count(*) filter (where o.pipeline = 'H_RESEARCH_UNVERIFIED'),
    'GLOBAL_REVIEW', count(*) filter (where o.pipeline = 'GLOBAL_REVIEW'),
    'EXCLUDED', count(*) filter (where o.pipeline = 'EXCLUDED'),
    'awaiting_review', count(*) filter (where o.stage in ('discovered', 'needs_review') and o.pipeline <> 'EXCLUDED'),
    'contacted', count(*) filter (where o.stage in ('contacted', 'replied', 'meeting_scheduled', 'proposal_sent', 'negotiation', 'won')),
    'replied', count(*) filter (where o.stage in ('replied', 'meeting_scheduled', 'proposal_sent', 'negotiation', 'won')),
    'proposals', count(*) filter (where o.stage in ('proposal_sent', 'negotiation', 'won')),
    'won', count(*) filter (where o.stage = 'won'),
    'revenue', coalesce(sum(o.deal_value) filter (where o.stage = 'won'), 0),
    'acquisition_costs', (select coalesce(sum(c.amount), 0) from public.acquisition_costs c),
    'follow_ups_due', (select count(*) from public.follow_ups f where f.done_at is null and f.due_at <= now() + interval '1 day')
  )
  from public.opportunities o
$$;

create or replace function public.refresh_my_notifications()
returns integer
language plpgsql security definer set search_path = '' as $$
declare
  v_uid uuid := auth.uid();
  v_s record;
  v_n int;
begin
  if not public.is_member() then
    return 0;
  end if;
  insert into public.notifications (user_id, kind, title, body, link, dedupe_key)
  select v_uid, 'follow_up_due', 'Follow-up due: ' || f.title, o.title, '/opportunities/' || o.id, 'fu:' || f.id || ':' || f.due_at::date
    from public.follow_ups f join public.opportunities o on o.id = f.opportunity_id
   where f.done_at is null and f.due_at <= now() + interval '1 day' and coalesce(f.assignee_id, f.created_by) = v_uid
  on conflict do nothing;
  insert into public.notifications (user_id, kind, title, body, link, dedupe_key)
  select v_uid, 'follow_up_due', 'Follow-up date reached', o.title, '/opportunities/' || o.id, 'ofu:' || o.id || ':' || o.follow_up_at::date
    from public.opportunities o
   where o.follow_up_at <= now() + interval '1 day' and o.owner_id = v_uid and o.stage not in ('won', 'lost', 'archived')
  on conflict do nothing;
  for v_s in select * from public.saved_searches where user_id = v_uid and notify loop
    select count(*) into v_n from public.opportunities o
     where o.discovered_at > v_s.last_seen_at
       and (v_s.filters ->> 'pipeline' is null or o.pipeline = v_s.filters ->> 'pipeline')
       and (v_s.filters ->> 'source' is null or o.source_key = v_s.filters ->> 'source')
       and (v_s.filters ->> 'country' is null or o.country ilike v_s.filters ->> 'country')
       and (v_s.filters ->> 'verification' is null or o.verification = v_s.filters ->> 'verification')
       and (v_s.filters ->> 'q' is null or o.search @@ websearch_to_tsquery('simple', v_s.filters ->> 'q'));
    if v_n > 0 then
      insert into public.notifications (user_id, kind, title, body, link, dedupe_key)
      values (v_uid, 'saved_search_match', v_n || ' new match(es): ' || v_s.name, null, '/searches/' || v_s.id,
              'ss:' || v_s.id || ':' || v_s.last_seen_at)
      on conflict do nothing;
    end if;
  end loop;
  if public.is_admin() then
    insert into public.notifications (user_id, kind, title, body, link, dedupe_key)
    select v_uid, 'source_failing', 'Source not working: ' || s.name, s.last_error, '/sources', 'src:' || s.key || ':' || s.last_run_at::date
      from public.sources s where s.enabled and s.last_status in ('failed', 'partial')
    on conflict do nothing;
  end if;
  return (select count(*) from public.notifications where user_id = v_uid and read_at is null);
end $$;

create or replace function public.purge_expired_excerpts()
returns integer
language plpgsql security definer set search_path = '' as $$
declare
  v_n int;
begin
  if not public.is_admin() then
    raise exception 'admins only' using errcode = '42501';
  end if;
  update public.opportunities
     set body_excerpt = null, requirement_summary = null, meta = meta || jsonb_build_object('excerpt_purged_at', now())
   where retain_until < now() and stage in ('discovered', 'needs_review', 'archived') and body_excerpt is not null;
  get diagnostics v_n = row_count;
  update public.evidence e set excerpt = null
    from public.opportunities o where o.id = e.opportunity_id and o.body_excerpt is null and e.kind = 'source_fact';
  return v_n;
end $$;

-- ----------------------------------------------------------------------------- analytics view (RLS of the caller applies)
create or replace view public.source_performance with (security_invoker = true) as
select s.key as source_key, s.name, s.family, s.permission_status, s.enabled, s.automated, s.last_status, s.last_run_at, s.last_success_at,
       s.last_error, s.next_run_at, s.monthly_budget_usd,
       count(o.id) as records,
       count(o.id) filter (where o.technical_relevance = 'relevant') as relevant,
       count(o.id) filter (where o.buying_intent in ('explicit_hire_request', 'quote_request', 'recommendation_request', 'partner_search', 'paid_bounty')) as explicit_buyers,
       count(o.id) filter (where o.contact_permission in ('reply_in_thread_invited', 'in_platform_only', 'per_platform_rules', 'procurement_portal')) as contactable,
       count(o.id) filter (where o.verification in ('api_verified', 'reviewer_verified')) as verified,
       count(o.id) filter (where o.stage not in ('discovered', 'needs_review')) as reviewed,
       count(o.id) filter (where o.stage in ('contacted', 'replied', 'meeting_scheduled', 'proposal_sent', 'negotiation', 'won')) as contacted,
       count(o.id) filter (where o.stage in ('replied', 'meeting_scheduled', 'proposal_sent', 'negotiation', 'won')) as conversations,
       count(o.id) filter (where o.stage in ('meeting_scheduled', 'proposal_sent', 'negotiation', 'won')) as meetings,
       count(o.id) filter (where o.stage in ('proposal_sent', 'negotiation', 'won')) as proposals,
       count(o.id) filter (where o.stage = 'won') as won,
       coalesce(sum(o.deal_value) filter (where o.stage = 'won'), 0) as revenue,
       (select coalesce(sum(c.amount), 0) from public.acquisition_costs c where c.source_key = s.key) as acquisition_costs,
       (select coalesce(sum(r.est_cost_usd), 0) from public.discovery_runs r where r.source_key = s.key) as est_api_cost_usd,
       (select count(*) from public.discovery_runs r where r.source_key = s.key) as runs
  from public.sources s
  left join public.opportunities o on o.source_key = s.key and o.duplicate_of is null
 group by s.key;

-- ----------------------------------------------------------------------------- triggers
drop trigger if exists opportunities_touch on public.opportunities;
create trigger opportunities_touch before update on public.opportunities for each row execute function public.touch_updated_at();
drop trigger if exists sources_touch on public.sources;
create trigger sources_touch before update on public.sources for each row execute function public.touch_updated_at();
drop trigger if exists opportunities_activity on public.opportunities;
create trigger opportunities_activity before update on public.opportunities for each row execute function public.opportunity_activity();

do $$
declare t text;
begin
  foreach t in array array['opportunities', 'classifications', 'sources', 'members', 'notes', 'proposals', 'acquisition_costs',
                           'contact_channels', 'ingest_tokens', 'app_settings', 'companies', 'follow_ups'] loop
    execute format('drop trigger if exists %I on public.%I', t || '_audit', t);
    execute format('create trigger %I after insert or update or delete on public.%I for each row execute function public.audit_row()', t || '_audit', t);
  end loop;
end $$;
