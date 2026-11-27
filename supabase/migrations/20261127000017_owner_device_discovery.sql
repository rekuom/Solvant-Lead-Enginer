-- Solvant Signal Engine — private-tool access and "Run discovery" from the dashboard.
-- The owner's trusted device holds a persistent Supabase session (no daily login). Discovery actions that the scheduled
-- task performs with its ingest token may now also be performed by a signed-in editor/admin (the owner), so the dashboard's
-- Run discovery button needs no extra credential in the browser or on the server. Anonymous callers remain blocked.

create or replace function solvant._discovery_token_ok(p_token text)
returns boolean
language sql stable security definer set search_path = '' as $$
  select solvant.can_edit()
      or exists (select 1 from solvant.ingest_tokens
                  where token_hash = encode(sha256(convert_to(coalesce(
                          coalesce(nullif(p_token, ''), nullif(current_setting('request.headers', true), '')::json ->> 'x-signal-token'), ''),
                          'UTF8')), 'hex')
                    and revoked_at is null and 'discovery' = any (scopes));
$$;
revoke all on function solvant._discovery_token_ok(text) from public, anon, authenticated;

-- Discovery run started from the dashboard by the owner: same validation as agent-mode ingestion, recorded as 'manual'.
create or replace function solvant.member_ingest_discovery(p_run jsonb, p_items jsonb)
returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_results text[] := '{}';
  v_item jsonb;
  v_log jsonb;
begin
  if not solvant.can_edit() then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  if jsonb_typeof(coalesce(p_items, '[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_items, '[]'::jsonb)) > 500 then
    raise exception 'items must be an array of at most 500 records' using errcode = '22023';
  end if;
  for v_log in select * from jsonb_array_elements(coalesce(p_run -> 'logs', '[]'::jsonb)) loop
    if exists (select 1 from solvant.sources where key = v_log ->> 'source_key') then
      insert into solvant.discovery_runs (source_key, origin, external_run_id, started_at, finished_at, status, requests, records, detail)
      values (v_log ->> 'source_key', 'manual', 'dashboard-run-discovery', now(), now(),
              case when v_log ->> 'status' in ('ok', 'partial', 'failed', 'skipped') then v_log ->> 'status' else 'ok' end,
              coalesce((v_log ->> 'requests')::int, 0), coalesce((v_log ->> 'records')::int, 0), coalesce(v_log -> 'counts', '{}'::jsonb));
    end if;
  end loop;
  for v_item in select * from jsonb_array_elements(coalesce(p_items, '[]'::jsonb)) loop
    v_results := v_results || solvant._ingest_item(v_item, 'discovery', null,
                                                   array['permitted', 'restricted', 'manual_only', 'unknown', 'licensed']);
  end loop;
  return solvant._tally(v_results);
end $$;

revoke all on function solvant.member_ingest_discovery(jsonb, jsonb) from public, anon;
grant execute on function solvant.member_ingest_discovery(jsonb, jsonb) to authenticated;

insert into solvant.schema_migrations (version) values ('20261127000017') on conflict do nothing;
