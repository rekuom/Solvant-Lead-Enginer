-- Solvant Signal Engine — commercial actionability.
-- 1. Proposal drafts prepared by the scheduled Claude task are stored privately here (never in the repository) and are
--    never sent: a human reviews, edits and submits them on the platform, then marks them submitted.
-- 2. The task re-checks open board listings daily and records what the source itself confirms (open / closed / removed).
-- 3. sales_funnel() keeps discovery counts separate from real buyer opportunities and actual sales progress.

alter table solvant.proposals add column if not exists body text check (body is null or char_length(body) <= 8000);
alter table solvant.proposals add column if not exists origin text not null default 'human' check (origin in ('human', 'claude_draft'));

create or replace function solvant._discovery_token_ok(p_token text)
returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from solvant.ingest_tokens
                  where token_hash = encode(sha256(convert_to(coalesce(
                          coalesce(nullif(p_token, ''), nullif(current_setting('request.headers', true), '')::json ->> 'x-signal-token'), ''),
                          'UTF8')), 'hex')
                    and revoked_at is null and 'discovery' = any (scopes));
$$;
revoke all on function solvant._discovery_token_ok(text) from public, anon, authenticated;

-- ---------------------------------------------------------------- proposal drafts (Claude-prepared, human-sent)
create or replace function solvant.save_proposal_drafts(p_token text, p_drafts jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_d jsonb;
  v_opp uuid;
  v_existing uuid;
  v_added int := 0;
  v_updated int := 0;
  v_missing int := 0;
  v_amount numeric;
begin
  if not solvant._discovery_token_ok(p_token) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  if jsonb_typeof(coalesce(p_drafts, '[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_drafts, '[]'::jsonb)) > 50 then
    raise exception 'drafts must be an array of at most 50 entries' using errcode = '22023';
  end if;
  for v_d in select * from jsonb_array_elements(coalesce(p_drafts, '[]'::jsonb)) loop
    select id into v_opp from solvant.opportunities
     where (canonical_url = v_d ->> 'url' or url = v_d ->> 'url') and duplicate_of is null
     order by discovered_at limit 1;
    if v_opp is null or coalesce(v_d ->> 'body', '') = '' then
      v_missing := v_missing + 1;
      continue;
    end if;
    v_amount := case when (v_d ->> 'amount') ~ '^[0-9]+(\.[0-9]{1,2})?$' then (v_d ->> 'amount')::numeric end;
    -- one live Claude draft per opportunity; anything a human has sent or decided is never touched
    select id into v_existing from solvant.proposals
     where opportunity_id = v_opp and origin = 'claude_draft' and status = 'draft' limit 1;
    if v_existing is null then
      insert into solvant.proposals (opportunity_id, title, amount, currency, status, body, origin, notes, created_by)
      values (v_opp, left(coalesce(nullif(v_d ->> 'title', ''), 'Proposal draft'), 200), v_amount,
              case when (v_d ->> 'currency') ~ '^[A-Z]{3}$' then v_d ->> 'currency' end, 'draft', left(v_d ->> 'body', 8000),
              'claude_draft', 'Prepared by the discovery task. Review and edit before submitting on the platform.', null);
      v_added := v_added + 1;
    else
      update solvant.proposals
         set title = left(coalesce(nullif(v_d ->> 'title', ''), title), 200), body = left(v_d ->> 'body', 8000),
             amount = coalesce(v_amount, amount),
             currency = coalesce(case when (v_d ->> 'currency') ~ '^[A-Z]{3}$' then v_d ->> 'currency' end, currency)
       where id = v_existing;
      v_updated := v_updated + 1;
    end if;
  end loop;
  return jsonb_build_object('added', v_added, 'updated', v_updated, 'not_found', v_missing);
end $$;

-- ---------------------------------------------------------------- daily availability re-check of board listings
create or replace function solvant.board_checks_due(p_token text, p_limit int default 40)
returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
  if not solvant._discovery_token_ok(p_token) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object('url', x.url, 'title', x.title) order by x.ord)
      from (select o.url, o.title,
                   row_number() over (order by (o.priority is distinct from 'A'), (o.priority is distinct from 'B'),
                                      coalesce(o.meta -> 'board_check' ->> 'checked_at', '') asc, o.rank_score desc) as ord
              from solvant.opportunities o
             where (o.meta ->> 'board_listing')::boolean is true
               and o.pipeline <> 'EXCLUDED' and o.duplicate_of is null
               and coalesce(o.source_state, '') not in ('closed', 'removed')
               and o.stage not in ('won', 'lost', 'archived')
               and o.discovered_at >= now() - interval '45 days') x
     where x.ord <= greatest(1, least(p_limit, 100))), '[]'::jsonb);
end $$;

create or replace function solvant.record_board_checks(p_token text, p_checks jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_c jsonb;
  v_status text;
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
    update solvant.opportunities o
       set meta = o.meta
                  || jsonb_build_object('board_check', (v_c - 'url' - 'requirements')
                       || jsonb_build_object('previous_status', o.meta -> 'board_check' ->> 'status'))
                  || case when v_status in ('closed', 'removed')
                          then jsonb_build_object('action', jsonb_build_object('type', 'none', 'label', 'No action: ' || v_status || ' at source',
                                                                               'where', o.meta -> 'action' ->> 'where'),
                                                  'next_action', 'No action: ' || v_status || ' at source')
                          else '{}'::jsonb end,
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

-- ---------------------------------------------------------------- shortlist for the daily commercial report (discovery token)
-- Best live buyer opportunities: open at source, priority A/B, with a concrete route (proposal / public reply / invited contact).
create or replace function solvant.commercial_shortlist(p_token text, p_limit int default 10)
returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
  if not solvant._discovery_token_ok(p_token) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  return coalesce((
    select jsonb_agg(x order by x.ord) from (
      select row_number() over (order by (o.priority is distinct from 'A'), o.rank_score desc, o.published_at desc nulls last) as ord,
             o.id, o.title, o.url, o.source_key, o.pipeline, o.priority, o.rank_score, o.country, o.budget_text,
             o.published_at::date as posted, o.stage, o.meta -> 'action' ->> 'label' as next_step,
             o.meta -> 'board_check' ->> 'status' as check_status, (o.meta -> 'board_check' ->> 'bids') as bids,
             o.meta -> 'board_check' ->> 'checked_at' as checked_at, o.suggested_service,
             exists (select 1 from solvant.proposals p where p.opportunity_id = o.id and p.status = 'draft') as draft_ready,
             exists (select 1 from solvant.proposals p where p.opportunity_id = o.id and p.status in ('sent', 'accepted', 'rejected')) as submitted
        from solvant.opportunities o
       where o.duplicate_of is null and o.priority in ('A', 'B')
         and o.pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER')
         and coalesce(o.source_state, '') not in ('closed', 'removed')
         and o.stage not in ('won', 'lost', 'archived')
         and coalesce(o.published_at, o.discovered_at) >= now() - interval '30 days'
         and coalesce(o.meta -> 'action' ->> 'type', '') in ('submit_proposal', 'reply_publicly', 'contact_permitted')
    ) x where x.ord <= greatest(1, least(p_limit, 50))), '[]'::jsonb);
end $$;

-- ---------------------------------------------------------------- the real sales funnel (members; RLS applies)
create or replace function solvant.sales_funnel(p_days int default 30)
returns jsonb
language sql stable security invoker set search_path = '' as $$
  with o as (
    select o.*, coalesce(o.meta -> 'board_check' ->> 'status', '') as check_status, coalesce(o.meta -> 'action' ->> 'type', '') as action_type
      from solvant.opportunities o where o.duplicate_of is null
  ), buyer as (
    select * from o where pipeline in ('A_DIRECT_SME', 'B_FREELANCE_PROJECT', 'C_AGENCY_PARTNER', 'GLOBAL_REVIEW')
  ), open_now as (
    select * from buyer
     where coalesce(source_state, '') not in ('closed', 'removed')
       and stage not in ('lost', 'archived', 'won')
       and coalesce(published_at, discovered_at) >= now() - interval '30 days'
       and (check_status in ('verified_open', 'verified_posted') or verification in ('api_verified', 'reviewer_verified', 'agent_reviewed'))
  ), props as (
    select p.*, o.stage from solvant.proposals p join o on o.id = p.opportunity_id
  )
  select jsonb_build_object(
    'days', p_days,
    'leads_found', (select count(*) from o where discovered_at >= now() - make_interval(days => greatest(1, least(p_days, 365)))),
    'buyer_opportunities', (select count(*) from buyer where discovered_at >= now() - make_interval(days => greatest(1, least(p_days, 365)))),
    'open_now', (select count(*) from open_now),
    'verified_open', (select count(*) from open_now where check_status = 'verified_open' or (verification in ('api_verified', 'reviewer_verified') and check_status = '')),
    'proposal_possible', (select count(*) from open_now where priority in ('A', 'B') and action_type in ('submit_proposal', 'reply_publicly', 'contact_permitted')),
    'drafts_ready', (select count(distinct opportunity_id) from props where status = 'draft'),
    'proposals_submitted', (select count(distinct id) from o where stage in ('proposal_sent', 'negotiation', 'won')
                              or id in (select opportunity_id from props where status in ('sent', 'accepted', 'rejected'))),
    'replies', (select count(*) from o where stage in ('replied', 'meeting_scheduled', 'negotiation', 'won')
                  or id in (select opportunity_id from solvant.activities where kind = 'reply')),
    'meetings', (select count(*) from o where stage in ('meeting_scheduled', 'negotiation')
                   or id in (select opportunity_id from solvant.activities where kind = 'meeting')),
    'won', (select count(*) from o where stage = 'won'),
    'revenue', (select coalesce(sum(deal_value), 0) from o where stage = 'won')
  );
$$;

-- counts only, for the daily report produced by the scheduled task
create or replace function solvant.funnel_for_report(p_token text)
returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
  if not solvant._discovery_token_ok(p_token) then
    raise exception 'invalid token' using errcode = '28000';
  end if;
  return solvant.sales_funnel(30);
end $$;

revoke all on function solvant.funnel_for_report(text) from public;
grant execute on function solvant.funnel_for_report(text) to anon, authenticated;
revoke all on function solvant.save_proposal_drafts(text, jsonb) from public;
revoke all on function solvant.board_checks_due(text, int) from public;
revoke all on function solvant.record_board_checks(text, jsonb) from public;
revoke all on function solvant.commercial_shortlist(text, int) from public;
revoke all on function solvant.sales_funnel(int) from public, anon;
grant execute on function solvant.save_proposal_drafts(text, jsonb), solvant.board_checks_due(text, int),
  solvant.record_board_checks(text, jsonb), solvant.commercial_shortlist(text, int) to anon, authenticated;
grant execute on function solvant.sales_funnel(int) to authenticated;

insert into solvant.schema_migrations (version) values ('20261123000011') on conflict do nothing;
