-- Solvant Signal Engine — discovery feedback for the scheduled Claude task (counts only, never lead content).
-- The agent calls this at the start of each run to see which queries and sources produced qualified opportunities
-- (and what humans did with them) over the last 30 days, and re-weights its search set accordingly.
-- Also: _ingest_item upgrades an existing unverified record to 'api_verified' when the source re-verifies it.

create or replace function solvant.discovery_feedback(p_token text default null, p_days int default 30)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_token text := coalesce(nullif(p_token, ''), nullif(current_setting('request.headers', true), '')::json ->> 'x-signal-token');
  v_ok boolean;
begin
  select exists (select 1 from solvant.ingest_tokens
                  where token_hash = encode(sha256(convert_to(coalesce(v_token, ''), 'UTF8')), 'hex')
                    and revoked_at is null and 'discovery' = any (scopes)) into v_ok;
  if not v_ok then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  return (
    with o as (
      select coalesce(nullif(meta ->> 'query_category', ''), '(none)') as q, source_key, pipeline, priority, stage, verification,
             exists (select 1 from solvant.classifications c where c.opportunity_id = o.id and c.is_current and c.engine = 'human') as human_corrected
        from solvant.opportunities o
       where discovered_at >= now() - make_interval(days => greatest(1, least(p_days, 180)))
         and meta ->> 'discovered_by' = 'claude_agent'
    ),
    agg as (
      select 'query' as dim, q as key, count(*) as total,
             count(*) filter (where pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER', 'GLOBAL_REVIEW')) as qualified,
             count(*) filter (where priority = 'A') as priority_a,
             count(*) filter (where pipeline = 'F_RECRUITMENT_SIGNAL') as employment,
             count(*) filter (where pipeline in ('EXCLUDED', 'H_RESEARCH_UNVERIFIED')) as not_qualified,
             count(*) filter (where verification = 'api_verified') as verified,
             count(*) filter (where stage not in ('discovered', 'needs_review', 'archived')) as progressed_by_human,
             count(*) filter (where human_corrected) as corrected_by_human,
             count(*) filter (where stage = 'won') as won
        from o group by q
      union all
      select 'source', source_key, count(*),
             count(*) filter (where pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER', 'GLOBAL_REVIEW')),
             count(*) filter (where priority = 'A'), count(*) filter (where pipeline = 'F_RECRUITMENT_SIGNAL'),
             count(*) filter (where pipeline in ('EXCLUDED', 'H_RESEARCH_UNVERIFIED')), count(*) filter (where verification = 'api_verified'),
             count(*) filter (where stage not in ('discovered', 'needs_review', 'archived')), count(*) filter (where human_corrected),
             count(*) filter (where stage = 'won')
        from o group by source_key
    )
    select jsonb_build_object('days', p_days, 'generated_at', now(),
             'by_query', coalesce(jsonb_agg(to_jsonb(agg) - 'dim' order by agg.qualified desc, agg.total desc) filter (where dim = 'query'), '[]'::jsonb),
             'by_source', coalesce(jsonb_agg(to_jsonb(agg) - 'dim' order by agg.qualified desc, agg.total desc) filter (where dim = 'source'), '[]'::jsonb))
      from agg
  );
end $$;

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
           published_at = coalesce(published_at, (p_item ->> 'published_at')::timestamptz),
           -- automatic re-verification upgrades unverified records; a reviewer's verification is never overwritten
           verification = case when v_ver = 'api_verified' and verification not in ('api_verified', 'reviewer_verified')
                               then 'api_verified' else verification end,
           body_excerpt = case when v_ver = 'api_verified' and verification not in ('api_verified', 'reviewer_verified')
                               then coalesce(left(p_item ->> 'body_excerpt', 4000), body_excerpt) else body_excerpt end
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

revoke all on function solvant._ingest_item(jsonb, text, uuid, text[]) from public, anon, authenticated;
revoke all on function solvant.discovery_feedback(text, int) from public;
grant execute on function solvant.discovery_feedback(text, int) to anon, authenticated;

insert into solvant.schema_migrations (version) values ('20261119000006') on conflict do nothing;
