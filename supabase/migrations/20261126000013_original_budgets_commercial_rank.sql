-- Preserve the buyer's original budget and rank the shortlist commercially.
--
-- 1. Re-ingesting a known lead now fills budget_text (it used to be set only on the first insert). The board-verified amount
--    (meta.board_check.budget, read from the listing page in the buyer's own currency) wins over list-card text; the replaced
--    value is kept in meta.budget_previous. A conversion or estimate never replaces a stated budget (value_gbp_est is ranking only).
-- 2. record_board_checks sets budget_text from the board's own budget, keeping the previous value.
-- 3. Backfill: board-verified budgets, and budgets stated verbatim in forum posts ("Budget: $1,000 (...)").
-- 4. commercial_shortlist ranks by a commercial score (fit, value, route, competition, open status, freshness) instead of the
--    A/B/C priority, includes priority C, returns the score parts, a status label and review flags.
-- 5. daily_changes splits the day's changes into new buyers, updated leads, agency partnerships and employment signals.

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
  v_budget text;
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
    v_budget := coalesce(nullif(p_item #>> '{meta,board_check,budget}', ''), nullif(v_existing.meta #>> '{board_check,budget}', ''),
                         nullif(p_item ->> 'budget_text', ''), v_existing.budget_text);
    update solvant.opportunities
       set last_seen_at = now(),
           source_state = coalesce(p_item ->> 'source_state', source_state),
           published_at = coalesce(published_at, (p_item ->> 'published_at')::timestamptz),
           -- automatic re-verification upgrades unverified records; a reviewer's verification is never overwritten
           verification = case when v_ver = 'api_verified' and verification not in ('api_verified', 'reviewer_verified')
                               then 'api_verified' else verification end,
           body_excerpt = case when v_ver = 'api_verified' and verification not in ('api_verified', 'reviewer_verified')
                               then coalesce(left(p_item ->> 'body_excerpt', 4000), body_excerpt) else body_excerpt end,
           -- the buyer's own budget: board-verified first, then the stated amount; never a conversion or estimate
           budget_text = left(v_budget, 120),
           meta = meta
                  || case when v_budget is distinct from v_existing.budget_text and v_existing.budget_text is not null
                          then jsonb_build_object('budget_previous', v_existing.budget_text) else '{}'::jsonb end
                  || jsonb_strip_nulls(jsonb_build_object('budget', v_budget,
                                                          'board_check', p_item #> '{meta,board_check}',
                                                          'value_gbp_est', p_item #> '{meta,value_gbp_est}'))
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


-- ---------------------------------------------------------------- board re-check also corrects the budget
create or replace function solvant.record_board_checks(p_token text, p_checks jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_c jsonb;
  v_status text;
  v_budget text;
  v_n int := 0;
  v_closed int := 0;
begin
  if not solvant._discovery_token_ok(p_token) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  if jsonb_typeof(coalesce(p_checks, '[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_checks, '[]'::jsonb)) > 100 then
    raise exception 'checks must be an array of at most 100 entries' using errcode = '22023';
  end if;
  for v_c in select * from jsonb_array_elements(coalesce(p_checks, '[]'::jsonb)) loop
    v_status := v_c ->> 'status';
    continue when v_status is null or v_status not in ('verified_open', 'verified_posted', 'reachable_unconfirmed', 'closed', 'removed', 'unreachable');
    v_budget := left(nullif(btrim(v_c ->> 'budget'), ''), 120);
    update solvant.opportunities o
       set meta = o.meta
                  || jsonb_build_object('board_check', (v_c - 'url' - 'requirements')
                       || jsonb_build_object('previous_status', o.meta -> 'board_check' ->> 'status'))
                  || case when v_budget is not null and o.budget_text is not null and o.budget_text is distinct from v_budget
                          then jsonb_build_object('budget_previous', o.budget_text) else '{}'::jsonb end
                  || case when v_budget is not null then jsonb_build_object('budget', v_budget) else '{}'::jsonb end
                  || case when v_status in ('closed', 'removed')
                          then jsonb_build_object('action', jsonb_build_object('type', 'none', 'label', 'No action: ' || v_status || ' at source',
                                                                               'where', o.meta -> 'action' ->> 'where'),
                                                  'next_action', 'No action: ' || v_status || ' at source')
                          when not (o.meta ? 'action') and o.pipeline in ('B_FREELANCE_PROJECT', 'GLOBAL_REVIEW')
                          then jsonb_build_object('action', jsonb_build_object('type', 'submit_proposal', 'where', 'the project board',
                                                                               'label', 'Submit a proposal on the project board; contact stays in-platform'),
                                                  'next_action', 'Submit a proposal on the project board; contact stays in-platform')
                          else '{}'::jsonb end,
           budget_text = coalesce(v_budget, o.budget_text),
           source_state = case v_status when 'closed' then 'closed' when 'removed' then 'removed' when 'verified_open' then 'open'
                                        else o.source_state end,
           published_at = coalesce(o.published_at, (case when (v_c ->> 'posted_at') ~ '^\d{4}-\d{2}-\d{2}$' then (v_c ->> 'posted_at')::timestamptz end))
     where (o.meta ->> 'board_listing')::boolean is true and (o.url = v_c ->> 'url' or o.canonical_url = v_c ->> 'url');
    if found then
      v_n := v_n + 1;
      if v_status in ('closed', 'removed') then v_closed := v_closed + 1; end if;
    end if;
  end loop;
  return jsonb_build_object('recorded', v_n, 'closed_or_removed', v_closed);
end $$;

-- ---------------------------------------------------------------- backfill original budgets
update solvant.opportunities
   set meta = meta || case when budget_text is not null then jsonb_build_object('budget_previous', budget_text) else '{}'::jsonb end
                   || jsonb_build_object('budget', meta #>> '{board_check,budget}'),
       budget_text = left(meta #>> '{board_check,budget}', 120)
 where nullif(meta #>> '{board_check,budget}', '') is not null
   and budget_text is distinct from meta #>> '{board_check,budget}';

-- a budget the buyer states in the post itself, verbatim (currency symbol required; nothing estimated)
update solvant.opportunities
   set budget_text = left(regexp_replace(m[1], '\s+', ' ', 'g'), 120),
       meta = meta || jsonb_build_object('budget', left(regexp_replace(m[1], '\s+', ' ', 'g'), 60), 'budget_source', 'stated in post')
  from (select id as mid,
               regexp_match(coalesce(title, '') || ' ' || coalesce(body_excerpt, ''),
                 'budget\s*(?:is|of)?\s*[:\-–]?\s*:?\s*([$£€][0-9][0-9,.]*\s?[kK]?(?:\s*(?:-|–|to)\s*[$£€]?[0-9][0-9,.]*\s?[kK]?)?(?:\s*/\s?h(?:ou)?r)?(?:\s*\([^)]{1,60}\))?)',
                 'i') as m
          from solvant.opportunities
         where budget_text is null and nullif(meta #>> '{board_check,budget}', '') is null) s
 where id = s.mid and s.m is not null;

-- ranking value (never shown as a price) for euro budgets written with a space as thousands separator ("10 000 € et plus"):
-- the old parser read them as 10 € and 1 €; recompute from the largest amount at the same rough EUR rate the engine uses
update solvant.opportunities o
   set meta = o.meta || jsonb_build_object('value_gbp_est', round(v.amount * 0.85, 2))
  from (select id, max(n[1]::numeric) as amount
          from solvant.opportunities,
               regexp_matches(regexp_replace(budget_text, '(\d)[[:space:]  ]+(\d{3})(?!\d)', '\1\2', 'g'), '(\d+)', 'g') as n
         where budget_text ~ '\d[[:space:]  ]\d{3}' and budget_text like '%€%'
         group by id) v
 where o.id = v.id;

-- ---------------------------------------------------------------- commercial shortlist (discovery token)
-- Ranked by a commercial score, not by the A/B/C priority. Each part is 0-5:
--   fit (rank_score/20), value (value_gbp_est buckets; unknown is neutral), route (public reply / invited contact 5, marketplace
--   proposal 2 because it needs a freelancer account), competition (visible offers; forum posts without visible offers 4),
--   status (confirmed open 5, forum requirement 3, listing exists 2), freshness (age).
create or replace function solvant.commercial_shortlist(p_token text, p_limit int default 10)
returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
  if not solvant._discovery_token_ok(p_token) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  return coalesce((
    select jsonb_agg(to_jsonb(y) - 'ord' order by y.ord) from (
      select row_number() over (order by s.commercial_score desc, s.published_at desc nulls last) as ord,
             s.id, s.title, s.url, s.source_key, s.pipeline, s.priority, s.rank_score, s.country, s.budget_text, s.posted, s.stage,
             s.next_step, s.check_status, s.bids, s.checked_at, s.suggested_service, s.draft_ready, s.submitted, s.status_label,
             s.commercial_score, s.is_new,
             jsonb_build_object('fit', s.fit_s, 'value', s.value_s, 'route', s.route_s, 'competition', s.comp_s, 'status', s.status_s,
                                'freshness', s.fresh_s) as score_parts,
             array_remove(array[
               case when s.bids >= 50 then 'heavily contested (' || s.bids || ' offers)' end,
               case when s.value_est is not null and s.value_est < 500 then 'low value for the likely effort' end,
               case when s.budget_text is null then 'budget not stated' end,
               case when s.route_s < 5 then 'needs a freelancer account on ' || coalesce(s.source_key, 'the board') end,
               case when s.legal then 'legal/terms review (personal data, scraping, health data or WhatsApp automation)' end
             ], null) as flags
        from (
          select b.*,
                 round(20 * (0.25 * b.fit_s + 0.20 * b.value_s + 0.15 * b.route_s + 0.15 * b.comp_s + 0.15 * b.status_s + 0.10 * b.fresh_s))::int
                   as commercial_score
            from (
              select o.id, o.title, o.url, o.source_key, o.pipeline, o.priority, o.rank_score, o.country, o.budget_text, o.published_at,
                     o.published_at::date as posted, o.stage, o.suggested_service, o.meta -> 'action' ->> 'label' as next_step,
                     o.meta -> 'board_check' ->> 'status' as check_status, o.meta -> 'board_check' ->> 'checked_at' as checked_at,
                     n.bids, n.value_est,
                     o.discovered_at >= now() - interval '24 hours' as is_new,
                     exists (select 1 from solvant.proposals p where p.opportunity_id = o.id and p.status = 'draft') as draft_ready,
                     exists (select 1 from solvant.proposals p where p.opportunity_id = o.id and p.status in ('sent', 'accepted', 'rejected')) as submitted,
                     case when o.meta -> 'board_check' ->> 'status' = 'verified_open' then 'confirmed_open'
                          when coalesce((o.meta ->> 'board_listing')::boolean, false) then 'exists'
                          else 'requirement_stated' end as status_label,
                     least(5.0, greatest(0, coalesce(o.rank_score, 0)) / 20.0) as fit_s,
                     case when n.value_est is null then 2.5 when n.value_est >= 5000 then 5 when n.value_est >= 2000 then 4
                          when n.value_est >= 1000 then 3 when n.value_est >= 500 then 2 else 1 end as value_s,
                     case when o.meta -> 'action' ->> 'type' in ('reply_publicly', 'contact_permitted') then 5 else 2 end as route_s,
                     case when n.bids is null then case when coalesce((o.meta ->> 'board_listing')::boolean, false) then 3 else 4 end
                          when n.bids < 10 then 5 when n.bids < 25 then 4 when n.bids < 50 then 3 when n.bids < 100 then 2 else 1 end as comp_s,
                     case when o.meta -> 'board_check' ->> 'status' = 'verified_open' then 5
                          when coalesce((o.meta ->> 'board_listing')::boolean, false) then 2 else 3 end as status_s,
                     case when coalesce(o.published_at, o.discovered_at) >= now() - interval '3 days' then 5
                          when coalesce(o.published_at, o.discovered_at) >= now() - interval '7 days' then 4
                          when coalesce(o.published_at, o.discovered_at) >= now() - interval '14 days' then 3 else 1 end as fresh_s,
                     (coalesce(o.title, '') || ' ' || coalesce(o.body_excerpt, '')) ~* '(scrap|personal data|patient|medical|health data|whatsapp)' as legal
                from solvant.opportunities o
                cross join lateral (
                  select case when coalesce(o.meta #>> '{board_check,bids}', o.meta #>> '{facts,bid_count}', '') ~ '^\d+$'
                              then coalesce(o.meta #>> '{board_check,bids}', o.meta #>> '{facts,bid_count}')::int end as bids,
                         case when coalesce(o.meta ->> 'value_gbp_est', '') ~ '^\d+(\.\d+)?$' then (o.meta ->> 'value_gbp_est')::numeric end as value_est
                ) n
               where o.duplicate_of is null and o.priority in ('A', 'B', 'C')
                 and o.pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT')
                 and coalesce(o.source_state, '') not in ('closed', 'removed')
                 and o.stage not in ('won', 'lost', 'archived')
                 and coalesce(o.published_at, o.discovered_at) >= now() - interval '30 days'
                 and coalesce(o.meta -> 'action' ->> 'type', '') in ('submit_proposal', 'reply_publicly', 'contact_permitted')
            ) b
        ) s
    ) y where y.ord <= greatest(1, least(p_limit, 50))), '[]'::jsonb);
end $$;

-- ---------------------------------------------------------------- what changed since the last report (discovery token)
create or replace function solvant.daily_changes(p_token text, p_hours int default 24)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_since timestamptz := now() - make_interval(hours => greatest(1, least(coalesce(p_hours, 24), 24 * 14)));
begin
  if not solvant._discovery_token_ok(p_token) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  return (
    with c as (
      select o.id, o.title, o.url, o.pipeline, o.priority, o.budget_text, o.discovered_at, o.last_seen_at,
             case when o.discovered_at >= v_since and o.pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'GLOBAL_REVIEW') then 'new_buyers'
                  when o.discovered_at >= v_since and o.pipeline = 'C_AGENCY_PARTNER' then 'partners'
                  when o.discovered_at >= v_since and o.pipeline = 'F_RECRUITMENT_SIGNAL' then 'employment'
                  when o.discovered_at < v_since and o.last_seen_at >= v_since
                       and o.pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER', 'GLOBAL_REVIEW') then 'updated_leads'
             end as bucket
        from solvant.opportunities o
       where o.duplicate_of is null and (o.discovered_at >= v_since or o.last_seen_at >= v_since)
    )
    select jsonb_build_object('since', v_since) || coalesce(jsonb_object_agg(bucket, items), '{}'::jsonb)
      from (select bucket, jsonb_agg(jsonb_build_object('title', title, 'url', url, 'pipeline', pipeline, 'priority', priority,
                                                        'budget_text', budget_text) order by priority nulls last, discovered_at desc) as items
              from c where bucket is not null group by bucket) g
  );
end $$;

revoke all on function solvant._ingest_item(jsonb, text, uuid, text[]) from public, anon, authenticated;
revoke all on function solvant.record_board_checks(text, jsonb) from public;
revoke all on function solvant.commercial_shortlist(text, int) from public;
revoke all on function solvant.daily_changes(text, int) from public;
grant execute on function solvant.record_board_checks(text, jsonb), solvant.commercial_shortlist(text, int),
  solvant.daily_changes(text, int) to anon, authenticated;

insert into solvant.schema_migrations (version) values ('20261126000013') on conflict do nothing;
