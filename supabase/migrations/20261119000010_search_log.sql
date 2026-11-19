-- Solvant Signal Engine — search log for the scheduled discovery task.
-- Every WebSearch the task runs is counted per strategy (including searches that found nothing), so discovery_feedback can
-- rate strategies per search and the task can shift its search budget to productive strategies. Stores the search text,
-- strategy label, language and counts only: never lead content or personal data. Token scope: discovery.

create or replace function solvant.log_searches(p_token text, p_searches jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_token text := coalesce(nullif(p_token, ''), nullif(current_setting('request.headers', true), '')::json ->> 'x-signal-token');
  v_ok boolean;
  v_s jsonb;
  v_n int := 0;
  v_strategy text;
  v_query text;
begin
  select exists (select 1 from solvant.ingest_tokens
                  where token_hash = encode(sha256(convert_to(coalesce(v_token, ''), 'UTF8')), 'hex')
                    and revoked_at is null and 'discovery' = any (scopes)) into v_ok;
  if not v_ok then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  if jsonb_typeof(coalesce(p_searches, '[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_searches, '[]'::jsonb)) > 200 then
    raise exception 'searches must be an array of at most 200 entries' using errcode = '22023';
  end if;
  for v_s in select * from jsonb_array_elements(coalesce(p_searches, '[]'::jsonb)) loop
    v_strategy := lower(left(regexp_replace(coalesce(v_s ->> 'strategy', ''), '[^A-Za-z0-9 _-]', '', 'g'), 40));
    v_query := left(regexp_replace(coalesce(v_s ->> 'query', ''), '[[:cntrl:]]', ' ', 'g'), 300);
    continue when v_strategy = '' or v_query = '';
    insert into solvant.search_queries (query_id, provider, category, market, lang, query, runs, verified_results, last_run_at)
    values ('ws:' || md5(v_strategy || '|' || lower(v_query)), 'claude_websearch', v_strategy, left(v_s ->> 'market', 20),
            left(v_s ->> 'lang', 10), v_query, 1, greatest(0, least(coalesce((v_s ->> 'kept')::int, 0), 100)), now())
    on conflict (query_id) do update
      set runs = solvant.search_queries.runs + 1,
          verified_results = solvant.search_queries.verified_results + excluded.verified_results,
          last_run_at = now();
    v_n := v_n + 1;
  end loop;
  return jsonb_build_object('logged', v_n);
end $$;

revoke all on function solvant.log_searches(text, jsonb) from public;
grant execute on function solvant.log_searches(text, jsonb) to anon, authenticated;

-- feedback: adds per-strategy search counts (searches run, candidates kept) alongside the outcome counts
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
         and (discovered_via = 'claude_web_search' or meta ->> 'discovered_by' = 'claude_agent')
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
             'by_strategy_searches', (select coalesce(jsonb_agg(jsonb_build_object('key', s.category, 'searches', s.runs, 'kept', s.kept)
                                              order by s.category), '[]'::jsonb)
                                        from (select category, sum(runs)::int as runs, sum(verified_results)::int as kept
                                                from solvant.search_queries
                                               where provider = 'claude_websearch'
                                                 and last_run_at >= now() - make_interval(days => greatest(1, least(p_days, 180)))
                                               group by category) s),
             'by_query', coalesce(jsonb_agg(to_jsonb(agg) - 'dim' order by agg.qualified desc, agg.total desc) filter (where dim = 'query'), '[]'::jsonb),
             'by_source', coalesce(jsonb_agg(to_jsonb(agg) - 'dim' order by agg.qualified desc, agg.total desc) filter (where dim = 'source'), '[]'::jsonb))
      from agg
  );
end $$;

revoke all on function solvant.discovery_feedback(text, int) from public;
grant execute on function solvant.discovery_feedback(text, int) to anon, authenticated;

insert into solvant.schema_migrations (version) values ('20261119000010') on conflict do nothing;
