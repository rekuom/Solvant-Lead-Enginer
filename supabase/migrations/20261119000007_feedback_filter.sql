-- Solvant Signal Engine — discovery_feedback also recognises agent leads by the discovered_via column
-- (the per-record meta marker was not retained by the item mapper before 2026-11-19). Counts only; no lead content.

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
             'by_query', coalesce(jsonb_agg(to_jsonb(agg) - 'dim' order by agg.qualified desc, agg.total desc) filter (where dim = 'query'), '[]'::jsonb),
             'by_source', coalesce(jsonb_agg(to_jsonb(agg) - 'dim' order by agg.qualified desc, agg.total desc) filter (where dim = 'source'), '[]'::jsonb))
      from agg
  );
end $$;

revoke all on function solvant.discovery_feedback(text, int) from public;
grant execute on function solvant.discovery_feedback(text, int) to anon, authenticated;

insert into solvant.schema_migrations (version) values ('20261119000007') on conflict do nothing;
