-- Security and behaviour tests for the Solvant schema. Every check raises on failure (psql -v ON_ERROR_STOP=1).
\set QUIET on
insert into auth.users values
  ('00000000-0000-0000-0000-00000000000a', 'admin@example.invalid'),
  ('00000000-0000-0000-0000-00000000000e', 'editor@example.invalid'),
  ('00000000-0000-0000-0000-00000000000b', 'viewer@example.invalid'),
  ('00000000-0000-0000-0000-0000000000ff', 'stranger@example.invalid');

create temp table t_codes (k text primary key, v text);
grant all on t_codes to authenticated, anon;
insert into t_codes select 'boot', public.create_bootstrap_code();

create function pg_temp.as_user(p uuid) returns void language plpgsql as $$
begin
  perform set_config('request.jwt.claims', json_build_object('sub', p, 'role', 'authenticated')::text, false);
  execute 'set role authenticated';
end $$;
create function pg_temp.expect_error(p_sql text, p_label text) returns void language plpgsql as $$
begin
  begin
    execute p_sql;
  exception when others then
    raise notice 'ok   % (blocked: %)', p_label, sqlerrm;
    return;
  end;
  raise exception 'FAIL % : statement succeeded but should have been blocked', p_label;
end $$;
create function pg_temp.check(p_cond boolean, p_label text) returns void language plpgsql as $$
begin
  if not coalesce(p_cond, false) then raise exception 'FAIL %', p_label; end if;
  raise notice 'ok   %', p_label;
end $$;
grant execute on all functions in schema pg_temp to anon, authenticated;

-- 1. anonymous access ------------------------------------------------------------------------------
set role anon;
select pg_temp.expect_error('select * from public.opportunities', 'anon cannot read opportunities');
select pg_temp.expect_error('select * from public.sources', 'anon cannot read sources');
select pg_temp.expect_error($q$select public.save_intake('{}', '[]')$q$, 'anon cannot call save_intake');
select pg_temp.expect_error('select public.create_bootstrap_code()', 'anon cannot mint bootstrap codes');
select pg_temp.expect_error($q$select public.ingest_records('x', '{}', '[]')$q$, 'anon ingest needs a valid token');
reset role;

-- 2. signed-in but not a member ----------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-0000000000ff');
select pg_temp.check((select count(*) from public.sources) = 0, 'non-member sees no sources');
select pg_temp.expect_error($q$select public.save_intake('{"origin":"manual"}', '[]')$q$, 'non-member cannot save intake');
select pg_temp.expect_error($q$select public.claim_admin('wrong-code')$q$, 'wrong bootstrap code rejected');
select pg_temp.expect_error('select public.create_bootstrap_code()', 'authenticated cannot mint bootstrap codes');
reset role;

-- 3. bootstrap the owner as admin; code is single-use ------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.check(public.claim_admin((select v from t_codes where k = 'boot')), 'owner claims admin with one-time code');
select pg_temp.check(public.is_admin(), 'owner is admin');
select public.add_member('editor@example.invalid', 'editor');
select public.add_member('viewer@example.invalid', 'viewer');
insert into t_codes select 'ingest', public.create_ingest_token('github-actions', array['discovery']);
insert into t_codes select 'mail', public.create_ingest_token('inbound', array['inbound_email']);
select pg_temp.expect_error('select token_hash from public.ingest_tokens', 'token hashes are not selectable');
reset role;
select pg_temp.as_user('00000000-0000-0000-0000-0000000000ff');
select pg_temp.expect_error($q$select public.claim_admin((select v from t_codes where k = 'boot'))$q$, 'bootstrap code cannot be reused');
reset role;

-- 4. machine ingestion --------------------------------------------------------------------------------
set role anon;
select pg_temp.check((r ->> 'added')::int = 2 and (r ->> 'rejected')::int = 5, 'ingest: 2 added, 5 rejected')
  from (select public.ingest_records((select v from t_codes where k = 'ingest'),
    '{"logs":[{"source_key":"github_issues","status":"ok","requests":3,"records":2},{"source_key":"ted","status":"failed","error_kind":"http_503"}]}',
    '[{"source_key":"github_issues","url":"https://github.com/a/b/issues/1","canonical_url":"https://github.com/a/b/issues/1","title":"Need an n8n contractor","body_excerpt":"We are looking for a freelancer to build our CRM automation workflow quickly.","fingerprint":"fp1","verification":"api_verified","pipeline":"A_DIRECT_SME","priority":"A","dims":{"buying_intent":{"value":"explicit_hire_request"},"technical_relevance":{"value":"relevant"}}},
      {"source_key":"find_a_tender","url":"https://www.find-tender.service.gov.uk/Notice/000001-2026","title":"CRM integration","verification":"api_verified","pipeline":"E_PROCUREMENT"},
      {"source_key":"web_search_brave","url":"https://example.invalid/x","verification":"search_snippet_only","pipeline":"H_RESEARCH_UNVERIFIED"},
      {"source_key":"github_issues","url":"https://github.com/a/b/issues/9","verification":"fixture","pipeline":"A_DIRECT_SME"},
      {"source_key":"nope","url":"https://example.invalid/y","verification":"api_verified"},
      {"source_key":"gitlab_issues","url":"https://gitlab.com/x/-/issues/1","verification":"api_verified"},
      {"source_key":"github_issues","url":"http://insecure.invalid","verification":"api_verified"}]') r) t;
select pg_temp.check((r ->> 'updated')::int = 1 and (r ->> 'duplicates')::int = 1, 'ingest again: same URL updated, same content flagged duplicate')
  from (select public.ingest_records((select v from t_codes where k = 'ingest'), '{}',
    '[{"source_key":"github_issues","url":"https://github.com/a/b/issues/1","canonical_url":"https://github.com/a/b/issues/1","verification":"api_verified","pipeline":"A_DIRECT_SME","dims":{"buying_intent":{"value":"explicit_hire_request"},"technical_relevance":{"value":"relevant"}}},
      {"source_key":"github_issues","url":"https://github.com/c/d/issues/2","canonical_url":"https://github.com/c/d/issues/2","title":"copy","body_excerpt":"We are looking for a freelancer to build our CRM automation workflow quickly.","fingerprint":"fp1","verification":"api_verified","pipeline":"A_DIRECT_SME"}]') r) t;
select pg_temp.expect_error($q$select public.ingest_records((select v from t_codes where k = 'mail'), '{"scope":"discovery"}', '[]')$q$, 'token scope enforced');
reset role;

-- 5. viewer / editor permissions ------------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select pg_temp.check((select count(*) from public.opportunities) = 3, 'viewer reads opportunities');
select pg_temp.check((select (public.dashboard_counts() ->> 'all')::int) = 3, 'dashboard counts for members');
update public.opportunities set stage = 'contacted' where url = 'https://github.com/a/b/issues/1';
select pg_temp.check((select stage from public.opportunities where url = 'https://github.com/a/b/issues/1') = 'needs_review', 'viewer update changes nothing (RLS)');
select pg_temp.expect_error($q$select public.override_classification((select id from public.opportunities limit 1), 'EXCLUDED', null, '{}', 'spam')$q$, 'viewer cannot reclassify');
select pg_temp.expect_error('select * from public.audit_log limit 1 for update', 'viewer cannot lock audit rows');
select pg_temp.check((select count(*) from public.audit_log) = 0, 'viewer sees no audit log');
reset role;

select pg_temp.as_user('00000000-0000-0000-0000-00000000000e');
update public.opportunities set stage = 'contacted', follow_up_at = now() - interval '1 hour', owner_id = auth.uid()
 where url = 'https://github.com/a/b/issues/1';
select pg_temp.check((select count(*) from public.activities a join public.opportunities o on o.id = a.opportunity_id
   where o.url = 'https://github.com/a/b/issues/1' and a.kind in ('stage_change', 'assignment', 'follow_up')) = 3, 'stage/owner/follow-up changes logged');
select pg_temp.expect_error($q$update public.opportunities set pipeline = 'EXCLUDED'$q$, 'pipeline column not directly editable');
select pg_temp.expect_error($q$update public.opportunities set verification = 'reviewer_verified'$q$, 'verification not directly editable');
select pg_temp.expect_error($q$update public.opportunities set body_excerpt = 'tampered'$q$, 'source facts immutable');
select public.override_classification((select id from public.opportunities where url = 'https://github.com/a/b/issues/1'),
       'B_FREELANCE_PROJECT', 'B', '{"engagement_type":"project"}', 'It is a marketplace-style fixed project');
select pg_temp.check((select count(*) from public.classifications c join public.opportunities o on o.id = c.opportunity_id
   where o.url = 'https://github.com/a/b/issues/1') = 2, 'override keeps history (2 classification rows)');
select pg_temp.check((select pipeline from public.opportunities where url = 'https://github.com/a/b/issues/1') = 'B_FREELANCE_PROJECT', 'override applied');
select pg_temp.expect_error($q$select public.override_classification((select id from public.opportunities limit 1), 'EXCLUDED', null, '{}', '')$q$, 'override requires a reason');
select public.verify_opportunity((select id from public.opportunities where url like '%Notice/000001-2026'), 'Opened the notice on Find a Tender; deadline confirmed');
select pg_temp.check((select verification from public.opportunities where url like '%Notice/000001-2026') = 'reviewer_verified', 'reviewer verification recorded');
insert into public.notes (opportunity_id, body) select id, 'Called via portal' from public.opportunities where url like '%issues/1';
select pg_temp.expect_error($q$insert into public.activities (opportunity_id, kind) select id, 'ingested' from public.opportunities limit 1$q$, 'cannot forge system activities');
update public.sources set enabled = true where key = 'reddit';
select pg_temp.check(not (select enabled from public.sources where key = 'reddit'), 'editor cannot change sources (RLS)');
select pg_temp.check(public.refresh_my_notifications() >= 1, 'follow-up reminder generated');
reset role;

-- intake as editor: manual-only source accepted, fixture rejected, prohibited rejected
select pg_temp.as_user('00000000-0000-0000-0000-00000000000e');
select pg_temp.check((r ->> 'added')::int = 1 and (r ->> 'rejected')::int = 2, 'browser intake: manual source added; fixture + prohibited rejected')
  from (select public.save_intake('{"origin":"paste","source_key":"linkedin"}',
    '[{"source_key":"linkedin","url":"https://www.linkedin.com/posts/acme-1","title":"Looking for a CRM partner","verification":"user_submitted","pipeline":"A_DIRECT_SME"},
      {"source_key":"linkedin","url":"https://www.linkedin.com/posts/acme-2","verification":"fixture"},
      {"source_key":"web_search_google_cse","url":"https://example.invalid/z","verification":"user_submitted"}]') r) t;
reset role;

-- 6. admin source controls and guards ---------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.expect_error($q$update public.sources set enabled = true where key = 'gitlab_issues'$q$, 'unknown-permission source cannot be enabled for automation');
select pg_temp.expect_error($q$update public.sources set enabled = true where key = 'web_search_brave'$q$, 'paid source cannot run without a budget');
update public.sources set enabled = true, monthly_budget_usd = 5 where key = 'web_search_brave';
select pg_temp.check((select enabled from public.sources where key = 'web_search_brave'), 'paid source enabled only with an approved budget');
select pg_temp.check((select count(*) from public.audit_log where table_name = 'sources') >= 1, 'admin sees audit log of source changes');
select pg_temp.check((select last_status from public.sources where key = 'ted') = 'failed', 'failed collector stays visibly failed');
select public.refresh_my_notifications();
select pg_temp.check(exists (select 1 from public.notifications where kind = 'source_failing'), 'failing source notification for admin');
reset role;

-- 7. notifications are private ---------------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select pg_temp.check((select count(*) from public.notifications) = 0, 'users only see their own notifications');
reset role;

\echo ALL SQL SECURITY TESTS PASSED
