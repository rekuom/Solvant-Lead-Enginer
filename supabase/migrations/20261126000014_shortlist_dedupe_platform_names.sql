-- Shortlist polish after the first live run of 013:
-- 1. the account flag names the platform ("Codeur", "PeopleperHour") instead of the internal source key;
-- 2. the same buyer posting on two forums is one lead: the later forum copy is linked as a duplicate of the one with the
--    draft and the public thread (reversible: duplicate_links keeps the pair; nothing is deleted).

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
               case when s.route_s < 5 then 'needs a freelancer account on ' || coalesce(s.platform, 'the board') end,
               case when s.legal then 'legal/terms review (personal data, scraping, health data or WhatsApp automation)' end
             ], null) as flags
        from (
          select b.*,
                 round(20 * (0.25 * b.fit_s + 0.20 * b.value_s + 0.15 * b.route_s + 0.15 * b.comp_s + 0.15 * b.status_s + 0.10 * b.fresh_s))::int
                   as commercial_score
            from (
              select o.id, o.title, o.url, o.source_key, o.pipeline, o.priority, o.rank_score, o.country, o.budget_text, o.published_at,
                     o.published_at::date as posted, o.stage, o.suggested_service, o.meta -> 'action' ->> 'label' as next_step,
                     coalesce(nullif(o.meta -> 'action' ->> 'where', 'the project board'), initcap(split_part(regexp_replace(o.url, '^https://(www\.)?', ''), '.', 1))) as platform,
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

do $$
declare
  v_keep uuid;
  v_dup uuid;
  v_pair text[];
begin
  foreach v_pair slice 1 in array array[
    array['https://community.make.com/t/airtable-automation-developer-needed/120066',
          'https://community.n8n.io/t/hiring-freelancer-for-airtable-workflow-remote/329131'],
    array['https://community.n8n.io/t/looking-for-n8n-contractors-for-ongoing-project-work/325902',
          'https://community.make.com/t/looking-for-make-com-contractors-for-ongoing-project-work/118999']]
  loop
    select id into v_keep from solvant.opportunities where canonical_url = v_pair[1];
    select id into v_dup from solvant.opportunities where canonical_url = v_pair[2];
    continue when v_keep is null or v_dup is null;
    insert into solvant.duplicate_links (opportunity_id, duplicate_of, reason) values (v_dup, v_keep, 'manual') on conflict do nothing;
    update solvant.opportunities set duplicate_of = v_keep where id = v_dup and duplicate_of is null;
    insert into solvant.activities (opportunity_id, kind, summary, detail)
    select v_dup, 'note', 'Same buyer as another forum post: linked as a duplicate', jsonb_build_object('duplicate_of', v_keep)
     where not exists (select 1 from solvant.activities where opportunity_id = v_dup and summary like 'Same buyer as another forum post%');
  end loop;
end $$;

revoke all on function solvant.commercial_shortlist(text, int) from public;
grant execute on function solvant.commercial_shortlist(text, int) to anon, authenticated;

insert into solvant.schema_migrations (version) values ('20261126000014') on conflict do nothing;
