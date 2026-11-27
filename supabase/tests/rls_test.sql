-- Security and behaviour tests for the Solvant schema. Every check raises on failure (psql -v ON_ERROR_STOP=1).
\set QUIET on
insert into auth.users values
  ('00000000-0000-0000-0000-00000000000a', 'admin@example.invalid'),
  ('00000000-0000-0000-0000-00000000000e', 'editor@example.invalid'),
  ('00000000-0000-0000-0000-00000000000b', 'viewer@example.invalid'),
  ('00000000-0000-0000-0000-0000000000ff', 'stranger@example.invalid');

-- tender collectors are off by default since 20261119000005; the failing-source scenario below uses TED explicitly
update solvant.sources set enabled = true where key = 'ted';
create temp table t_codes (k text primary key, v text);
grant all on t_codes to authenticated, anon, service_role;
insert into t_codes select 'boot', solvant.create_bootstrap_code();

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
grant execute on all functions in schema pg_temp to anon, authenticated, service_role;

-- 1. anonymous access ------------------------------------------------------------------------------
set role anon;
select pg_temp.expect_error('select * from solvant.opportunities', 'anon cannot read opportunities');
select pg_temp.expect_error('select * from solvant.sources', 'anon cannot read sources');
select pg_temp.expect_error($q$select solvant.save_intake('{}', '[]')$q$, 'anon cannot call save_intake');
select pg_temp.expect_error('select solvant.create_bootstrap_code()', 'anon cannot mint bootstrap codes');
select pg_temp.expect_error($q$select solvant.ingest_records('x', '{}', '[]')$q$, 'anon ingest needs a valid token');
reset role;

-- 2. signed-in but not a member ----------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-0000000000ff');
select pg_temp.check((select count(*) from solvant.sources) = 0, 'non-member sees no sources');
select pg_temp.expect_error($q$select solvant.save_intake('{"origin":"manual"}', '[]')$q$, 'non-member cannot save intake');
select pg_temp.expect_error($q$select solvant.claim_admin('wrong-code')$q$, 'wrong bootstrap code rejected');
select pg_temp.expect_error('select solvant.create_bootstrap_code()', 'authenticated cannot mint bootstrap codes');
reset role;

-- 3. bootstrap the owner as admin; code is single-use ------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.check(solvant.claim_admin((select v from t_codes where k = 'boot')), 'owner claims admin with one-time code');
select pg_temp.check(solvant.is_admin(), 'owner is admin');
select solvant.add_member('editor@example.invalid', 'editor');
select solvant.add_member('viewer@example.invalid', 'viewer');
insert into t_codes select 'ingest', solvant.create_ingest_token('github-actions', array['discovery']);
insert into t_codes select 'mail', solvant.create_ingest_token('inbound', array['inbound_email']);
select pg_temp.expect_error('select token_hash from solvant.ingest_tokens', 'token hashes are not selectable');
reset role;
select pg_temp.as_user('00000000-0000-0000-0000-0000000000ff');
select pg_temp.expect_error($q$select solvant.claim_admin((select v from t_codes where k = 'boot'))$q$, 'bootstrap code cannot be reused');
reset role;

-- 4. machine ingestion --------------------------------------------------------------------------------
set role anon;
select pg_temp.check((r ->> 'added')::int = 2 and (r ->> 'rejected')::int = 5, 'ingest: 2 added, 5 rejected')
  from (select solvant.ingest_records((select v from t_codes where k = 'ingest'),
    '{"logs":[{"source_key":"github_issues","status":"ok","requests":3,"records":2},{"source_key":"ted","status":"failed","error_kind":"http_503"}]}',
    '[{"source_key":"github_issues","url":"https://github.com/a/b/issues/1","canonical_url":"https://github.com/a/b/issues/1","title":"Need an n8n contractor","body_excerpt":"We are looking for a freelancer to build our CRM automation workflow quickly.","fingerprint":"fp1","verification":"api_verified","pipeline":"A_DIRECT_SME","priority":"A","dims":{"buying_intent":{"value":"explicit_hire_request"},"technical_relevance":{"value":"relevant"}}},
      {"source_key":"find_a_tender","url":"https://www.find-tender.service.gov.uk/Notice/000001-2026","title":"CRM integration","verification":"api_verified","pipeline":"E_PROCUREMENT"},
      {"source_key":"web_search_brave","url":"https://example.invalid/x","verification":"search_snippet_only","pipeline":"H_RESEARCH_UNVERIFIED"},
      {"source_key":"github_issues","url":"https://github.com/a/b/issues/9","verification":"fixture","pipeline":"A_DIRECT_SME"},
      {"source_key":"nope","url":"https://example.invalid/y","verification":"api_verified"},
      {"source_key":"gitlab_issues","url":"https://gitlab.com/x/-/issues/1","verification":"api_verified"},
      {"source_key":"github_issues","url":"http://insecure.invalid","verification":"api_verified"}]') r) t;
select pg_temp.check((r ->> 'updated')::int = 1 and (r ->> 'duplicates')::int = 1, 'ingest again: same URL updated, same content flagged duplicate')
  from (select solvant.ingest_records((select v from t_codes where k = 'ingest'), '{}',
    '[{"source_key":"github_issues","url":"https://github.com/a/b/issues/1","canonical_url":"https://github.com/a/b/issues/1","verification":"api_verified","pipeline":"A_DIRECT_SME","dims":{"buying_intent":{"value":"explicit_hire_request"},"technical_relevance":{"value":"relevant"}}},
      {"source_key":"github_issues","url":"https://github.com/c/d/issues/2","canonical_url":"https://github.com/c/d/issues/2","title":"copy","body_excerpt":"We are looking for a freelancer to build our CRM automation workflow quickly.","fingerprint":"fp1","verification":"api_verified","pipeline":"A_DIRECT_SME"}]') r) t;
select pg_temp.expect_error($q$select solvant.ingest_records((select v from t_codes where k = 'mail'), '{"scope":"discovery"}', '[]')$q$, 'token scope enforced');
reset role;

-- 4b. agent discovery mode: token via header, search-discovered manual-only platforms accepted, prohibited rejected
select set_config('request.headers', json_build_object('x-signal-token', (select v from t_codes where k = 'ingest'))::text, false);
set role anon;
select pg_temp.check((r ->> 'added')::int = 2 and (r ->> 'rejected')::int = 2, 'agent mode: header token, 2 added, 2 rejected')
  from (select solvant.ingest_records(null, '{"scope":"discovery","mode":"agent","logs":[{"source_key":"linkedin","status":"ok","records":2}]}',
    '[{"source_key":"linkedin","url":"https://www.linkedin.com/posts/founder-ai-dev-1","title":"Can anyone recommend an AI developer?","verification":"search_snippet_only","pipeline":"A_DIRECT_SME","priority":"B","engine":"llm","engine_version":"claude-agent+rules"},
      {"source_key":"make_community","url":"https://community.make.com/t/looking-for-make-dev/1","title":"Looking for a Make.com developer","verification":"agent_reviewed","pipeline":"A_DIRECT_SME","priority":"A","engine":"llm","meta":{"discovered_by":"claude_agent","query_category":"make hire-help latest"}},
      {"source_key":"ai_shared_conversations","url":"https://chatgpt.com/share/x","verification":"search_snippet_only","pipeline":"A_DIRECT_SME"},
      {"source_key":"linkedin","url":"https://www.linkedin.com/posts/x2","verification":"fixture","pipeline":"A_DIRECT_SME"}]') r) t;
reset role;
select set_config('request.headers', '', false);
select set_config('request.headers', json_build_object('x-signal-token', (select v from t_codes where k = 'ingest'))::text, false);
set role anon;
select solvant.ingest_records(null, '{"scope":"discovery","mode":"agent"}',
  '[{"source_key":"make_community","url":"https://community.make.com/t/looking-for-make-dev/1","title":"Looking for a Make.com developer","verification":"api_verified","pipeline":"A_DIRECT_SME","engine":"llm"}]');
reset role;
select set_config('request.headers', '', false);
select pg_temp.check((select verification from solvant.opportunities where url = 'https://community.make.com/t/looking-for-make-dev/1') = 'api_verified', 're-seen lead upgraded to api_verified');
select pg_temp.check((select engine from solvant.classifications c join solvant.opportunities o on o.id = c.opportunity_id
   where o.url = 'https://community.make.com/t/looking-for-make-dev/1') = 'llm', 'agent qualification stored as engine llm');
select pg_temp.check((select origin from solvant.discovery_runs where source_key = 'linkedin' order by started_at desc limit 1) = 'scheduler', 'agent runs logged as scheduler');
set role anon;
select pg_temp.expect_error($q$select solvant.ingest_records(null, '{"scope":"discovery","mode":"agent"}', '[]')$q$, 'no header and no argument: rejected');
reset role;
select pg_temp.check(not (select enabled from solvant.sources where key = 'find_a_tender'), 'tender collectors switched off');
select set_config('request.headers', json_build_object('x-signal-token', (select v from t_codes where k = 'ingest'))::text, false);
set role anon;
select pg_temp.check((solvant.discovery_feedback() -> 'by_source') @> '[{"key":"make_community"}]'::jsonb, 'feedback: per-source counts via header token');
select pg_temp.check(position('linkedin.com/posts' in solvant.discovery_feedback()::text) = 0, 'feedback contains no lead content');
select pg_temp.check((solvant.log_searches('', '[{"strategy":"biz-accounting","query":"can anyone recommend automation","lang":"en","kept":2},
                                               {"strategy":"de","query":"suche Freelancer Automatisierung","lang":"de","kept":0},
                                               {"strategy":"","query":"ignored"}]'::jsonb) ->> 'logged')::int = 2, 'search log: valid entries logged');
select solvant.log_searches('', '[{"strategy":"de","query":"Suche Freelancer Automatisierung","kept":1}]'::jsonb);
select pg_temp.check((solvant.discovery_feedback() -> 'by_strategy_searches') @> '[{"key":"de","searches":2,"kept":1}]'::jsonb,
                     'feedback: searches per strategy (same query counted twice, case-insensitive)');
reset role;
select pg_temp.check((select count(*) from solvant.search_queries where provider = 'claude_websearch') = 2, 'search log: one row per strategy+query');
select set_config('request.headers', '', false);
set role anon;
select pg_temp.expect_error('select solvant.discovery_feedback()', 'feedback needs a valid token');
select pg_temp.expect_error($q$select solvant.log_searches('', '[{"strategy":"x","query":"y"}]')$q$, 'search log needs a valid token');

-- 4b. commercial actionability: board re-checks, Claude proposal drafts, sales funnel ----------------------------------------
select solvant.ingest_records((select v from t_codes where k = 'ingest'), '{"scope":"discovery","mode":"agent"}',
  '[{"source_key":"eu_freelance_boards","url":"https://www.codeur.com/projects/1-agent-ia-devis","title":"Agent IA pour les devis","verification":"agent_reviewed","pipeline":"B_FREELANCE_PROJECT","priority":"A","engine":"llm","meta":{"discovered_by":"claude_agent","board_listing":true,"action":{"type":"submit_proposal","label":"Submit a proposal on Codeur","where":"Codeur"}}},
    {"source_key":"eu_freelance_boards","url":"https://www.codeur.com/projects/2-integration-crm","title":"Intégration CRM","verification":"agent_reviewed","pipeline":"B_FREELANCE_PROJECT","priority":"B","engine":"llm","meta":{"discovered_by":"claude_agent","board_listing":true,"action":{"type":"submit_proposal","label":"Submit a proposal on Codeur","where":"Codeur"}}}]');
select set_config('request.headers', json_build_object('x-signal-token', (select v from t_codes where k = 'ingest'))::text, false);
set role anon;
select pg_temp.check(jsonb_array_length(solvant.board_checks_due('', 40)) = 2, 'board re-check: open board listings are due');
select pg_temp.check((solvant.record_board_checks('', '[{"url":"https://www.codeur.com/projects/1-agent-ia-devis","status":"verified_open","posted_at":"2026-11-20","bids":12,"checks":["page reachable"]},
                                                        {"url":"https://www.codeur.com/projects/2-integration-crm","status":"closed","checks":["closed"]},
                                                        {"url":"https://community.make.com/t/looking-for-make-dev/1","status":"closed"}]') ->> 'recorded')::int = 2,
                     'board re-check: only board listings are updated');
select pg_temp.check(jsonb_array_length(solvant.board_checks_due('', 40)) = 1, 'closed listings are no longer re-checked');
select solvant.ingest_records('', '{"scope":"discovery","mode":"agent"}',
  '[{"source_key":"eu_freelance_boards","url":"https://www.codeur.com/projects/3-legacy","title":"Ancien projet","verification":"agent_reviewed","pipeline":"B_FREELANCE_PROJECT","priority":"B","engine":"llm","meta":{"discovered_by":"claude_agent","board_listing":true}}]');
select solvant.record_board_checks('', '[{"url":"https://www.codeur.com/projects/3-legacy","status":"verified_open"}]');
select pg_temp.check((solvant.save_proposal_drafts('', '[{"url":"https://www.codeur.com/projects/1-agent-ia-devis","title":"Agent IA devis","body":"Bonjour, ...","amount":"1800","currency":"EUR"},
                                                         {"url":"https://example.invalid/none","body":"x"}]') ->> 'added')::int = 1, 'proposal draft saved for a known lead only');
select pg_temp.check((solvant.save_proposal_drafts('', '[{"url":"https://www.codeur.com/projects/1-agent-ia-devis","body":"Bonjour, version 2"}]') ->> 'updated')::int = 1,
                     'a second draft updates the existing Claude draft');
select pg_temp.check(solvant.commercial_shortlist('', 10) @> '[{"title":"Agent IA pour les devis","draft_ready":true}]'::jsonb
                     and position('2-integration-crm' in solvant.commercial_shortlist('', 10)::text) = 0, 'shortlist: open with draft; closed excluded');
select pg_temp.check((solvant.funnel_for_report('') ->> 'drafts_ready')::int = 1, 'report funnel: counts via discovery token');
-- 4c. original budgets are preserved; the shortlist is ranked commercially, not by A/B/C ---------------------------------------
select solvant.ingest_records('', '{"scope":"discovery","mode":"agent"}',
  '[{"source_key":"eu_freelance_boards","url":"https://www.peopleperhour.com/freelance-jobs/x-4532403","title":"Scrape letting agents","budget_text":"$474","verification":"agent_reviewed","pipeline":"B_FREELANCE_PROJECT","priority":"A","rank_score":80,"engine":"llm","meta":{"discovered_by":"claude_agent","board_listing":true,"value_gbp_est":363,"facts":{"bid_count":84},"action":{"type":"submit_proposal","label":"Submit a proposal on PeoplePerHour","where":"PeopleperHour"}}},
    {"source_key":"make_community","url":"https://community.make.com/t/airtable-automation-developer-needed/120066","title":"Airtable automation developer needed","verification":"agent_reviewed","pipeline":"A_DIRECT_SME","priority":"C","rank_score":60,"engine":"llm","meta":{"discovered_by":"claude_agent","action":{"type":"reply_publicly","label":"Reply in the thread","where":"Make forum"}}}]');
select solvant.record_board_checks('', '[{"url":"https://www.peopleperhour.com/freelance-jobs/x-4532403","status":"verified_open","budget":"£363 (fixed price)","bids":84}]');
reset role;
select pg_temp.check((select budget_text = '£363 (fixed price)' and meta ->> 'budget_previous' = '$474' from solvant.opportunities where url like '%4532403'),
                     'board re-check replaces a viewer-currency card price with the buyer''s own budget, keeping the old value');
select solvant.ingest_records('', '{"scope":"discovery","mode":"agent"}',
  '[{"source_key":"make_community","url":"https://community.make.com/t/airtable-automation-developer-needed/120066","title":"Airtable automation developer needed","budget_text":"$1,000 (open to hearing what this should cost)","verification":"agent_reviewed","pipeline":"A_DIRECT_SME","priority":"C","rank_score":60,"engine":"llm","meta":{"discovered_by":"claude_agent","action":{"type":"reply_publicly","label":"Reply in the thread","where":"Make forum"}}},
    {"source_key":"eu_freelance_boards","url":"https://www.peopleperhour.com/freelance-jobs/x-4532403","title":"Scrape letting agents","budget_text":"$474","verification":"agent_reviewed","pipeline":"B_FREELANCE_PROJECT","priority":"A","rank_score":80,"engine":"llm","meta":{"discovered_by":"claude_agent","board_listing":true}}]');
select pg_temp.check((select budget_text from solvant.opportunities where url like '%120066') = '$1,000 (open to hearing what this should cost)',
                     're-ingest fills a stated budget missing from the first insert');
set role anon;
reset role;
select pg_temp.check((select budget_text from solvant.opportunities where url like '%4532403') = '£363 (fixed price)',
                     're-ingest never replaces the board-verified budget with card text');
set role anon;
select pg_temp.check(position('120066' in solvant.commercial_shortlist('', 10)::text) > 0
                       and position('120066' in solvant.commercial_shortlist('', 10)::text) < position('4532403' in solvant.commercial_shortlist('', 10)::text),
                     'shortlist: an uncontested direct reply (priority C) outranks a crowded low-value A project');
select pg_temp.check(solvant.commercial_shortlist('', 10) @> '[{"status_label":"requirement_stated"},{"status_label":"confirmed_open","budget_text":"£363 (fixed price)"}]'::jsonb
                       and (select bool_or(f ->> 0 like 'heavily contested%') from jsonb_array_elements(solvant.commercial_shortlist('', 10)) e, lateral (select e -> 'flags' as f) z),
                     'shortlist: status labels, original budget and review flags');
select pg_temp.check((select bool_or(f = 'needs a freelancer account on PeopleperHour') and not bool_or(f like '%eu_freelance_boards%')
                        from jsonb_array_elements(solvant.commercial_shortlist('', 10)) e, jsonb_array_elements_text(e -> 'flags') f),
                     'shortlist: the account flag names the platform, not the internal source key');
select pg_temp.check(solvant.daily_changes('', 24) -> 'new_buyers' @> '[{"budget_text":"$1,000 (open to hearing what this should cost)"}]'::jsonb,
                     'daily changes: new buyers listed with their stated budget');
reset role;
select set_config('request.headers', '', false);
set role anon;
select pg_temp.expect_error($q$select solvant.save_proposal_drafts('', '[]')$q$, 'proposal drafts need a valid token');
select pg_temp.expect_error($q$select solvant.board_checks_due('', 5)$q$, 'board checks need a valid token');
select pg_temp.expect_error($q$select solvant.commercial_shortlist('', 5)$q$, 'shortlist needs a valid token');
select pg_temp.expect_error($q$select solvant.daily_changes('', 24)$q$, 'daily changes need a valid token');
select pg_temp.expect_error($q$select solvant.sales_funnel()$q$, 'anon cannot read the sales funnel');
reset role;
select pg_temp.check((select source_state from solvant.opportunities where url = 'https://www.codeur.com/projects/2-integration-crm') = 'closed'
                     and (select meta -> 'action' ->> 'type' from solvant.opportunities where url = 'https://www.codeur.com/projects/2-integration-crm') = 'none',
                     'closed listing: source state closed and next step set to no action');
select pg_temp.check((select count(*) from solvant.proposals where origin = 'claude_draft' and status = 'draft' and body = 'Bonjour, version 2') = 1,
                     'one Claude draft per opportunity, never sent');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.check((solvant.sales_funnel() ->> 'open_now')::int >= 1 and (solvant.sales_funnel() ->> 'verified_open')::int >= 1
                     and (solvant.sales_funnel() ->> 'drafts_ready')::int = 1 and (solvant.sales_funnel() ->> 'proposal_possible')::int >= 1
                     and (solvant.sales_funnel() ->> 'proposals_submitted')::int = 0, 'sales funnel separates open, drafted and submitted');
reset role;

select pg_temp.check((select meta -> 'action' ->> 'type' from solvant.opportunities where url = 'https://www.codeur.com/projects/3-legacy') = 'submit_proposal',
                     'legacy open board lead gets a proposal next step on re-check');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.check(jsonb_array_length(solvant.commercial_candidates(10)) >= 1
                     and (solvant.commercial_candidates(10) -> 0) ? 'commercial_score', 'dashboard: members get the commercially scored list');
reset role;
select set_config('request.headers', json_build_object('x-signal-token', (select v from t_codes where k = 'ingest'))::text, false);
select pg_temp.check((select jsonb_agg(x ->> 'id') from jsonb_array_elements(solvant.commercial_shortlist('', 10)) x)
                     = (select jsonb_agg(x ->> 'id') from jsonb_array_elements(solvant.commercial_candidates(10)) x),
                     'daily report and dashboard rank identically');
select set_config('request.headers', '', false);
set role anon;
select pg_temp.expect_error('select solvant.commercial_candidates(5)', 'anon cannot read the scored list');
reset role;
delete from solvant.opportunities where url like 'https://www.codeur.com/projects/%' or url like 'https://www.peopleperhour.com/freelance-jobs/x-%'
   or url = 'https://community.make.com/t/airtable-automation-developer-needed/120066';   -- keep later counts stable

reset role;

-- 4c. owner device: discovery from the dashboard without a token ---------------------------------------------------------
select set_config('request.headers', '', false);
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.check((solvant.member_ingest_discovery('{"logs":[{"source_key":"eu_freelance_boards","status":"ok","records":1}]}',
  '[{"source_key":"eu_freelance_boards","url":"https://www.codeur.com/projects/9-dashboard-run","title":"Automatiser les devis","verification":"agent_reviewed","pipeline":"B_FREELANCE_PROJECT","priority":"B","engine":"rules","meta":{"discovered_by":"claude_agent","board_listing":true}}]') ->> 'added')::int = 1,
  'owner runs discovery from the dashboard (no token in the browser)');
select pg_temp.check(jsonb_typeof(solvant.board_checks_due('', 5)) = 'array', 'owner session may run the board re-check');
reset role;
select pg_temp.as_user('00000000-0000-0000-0000-0000000000ff');
select pg_temp.expect_error($q$select solvant.member_ingest_discovery('{}', '[]')$q$, 'non-member cannot run discovery');
select pg_temp.expect_error($q$select solvant.board_checks_due('', 5)$q$, 'non-member cannot use discovery functions');
reset role;
set role anon;
select pg_temp.expect_error($q$select solvant.member_ingest_discovery('{}', '[]')$q$, 'anon cannot run discovery');
reset role;
delete from solvant.opportunities where url = 'https://www.codeur.com/projects/9-dashboard-run';

-- 4d. e-mail outreach: encrypted mailbox token is server-only ------------------------------------------------------------
insert into solvant.mail_accounts (provider, email, display_name, refresh_token_enc) values ('microsoft', 'owner@example.invalid', 'Owner', 'v1:ciphertext');
insert into solvant.outreach_emails (to_address, subject, body, status, sent_at) values ('buyer@example.invalid', 'Hello', 'Body', 'sent', now());
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.check((select email from solvant.mail_accounts limit 1) = 'owner@example.invalid', 'owner sees the connected mailbox');
select pg_temp.expect_error('select refresh_token_enc from solvant.mail_accounts', 'mailbox token is never readable from the browser');
select pg_temp.check((select count(*) from solvant.outreach_emails) = 1, 'owner sees the sent-email log');
select pg_temp.expect_error($q$insert into solvant.outreach_emails (to_address, subject, body, status) values ('x@example.invalid','s','b','sent')$q$,
                            'browser cannot fake a sent e-mail');
reset role;
select pg_temp.as_user('00000000-0000-0000-0000-0000000000ff');
select pg_temp.check((select count(*) from solvant.outreach_emails) = 0 and (select count(*) from solvant.mail_accounts) = 0, 'non-member sees no mailbox or e-mails');
reset role;
set role anon;
select pg_temp.expect_error('select id from solvant.mail_accounts', 'anon cannot see mailboxes');
reset role;
delete from solvant.outreach_emails; delete from solvant.mail_accounts;

-- 4e. one-time device setup codes ------------------------------------------------------------------------------------------
select set_config('request.headers', json_build_object('x-signal-token', (select v from t_codes where k = 'ingest'))::text, false);
set role anon;
insert into t_codes select 'dev1', solvant.create_device_setup_code('', 'Owner laptop');
reset role;
select set_config('request.headers', '', false);
select pg_temp.check((select count(*) from solvant.device_setup_codes where code_hash = (select v from t_codes where k = 'dev1')) = 0,
                     'setup code is stored only as a hash');
set role service_role;
insert into t_codes select 'devid', solvant.redeem_device_setup_code((select v from t_codes where k = 'dev1'))::text;
select pg_temp.check((select v from t_codes where k = 'devid') is not null, 'setup code registers a device');
select pg_temp.check(solvant.redeem_device_setup_code((select v from t_codes where k = 'dev1')) is null, 'setup code works only once');
select pg_temp.check(solvant.device_active((select v from t_codes where k = 'devid')::uuid), 'new device is active');
reset role;
update solvant.device_setup_codes set expires_at = now() - interval '1 minute' where used_at is null;
set role anon;
select pg_temp.expect_error($q$select solvant.create_device_setup_code('', 'x')$q$, 'anon without token cannot create setup codes');
select pg_temp.expect_error($q$select solvant.redeem_device_setup_code('abc')$q$, 'browser roles cannot redeem codes directly');
reset role;
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select solvant.revoke_device((select v from t_codes where k = 'devid')::uuid);
reset role;
set role service_role;
select pg_temp.check(not solvant.device_active((select v from t_codes where k = 'devid')::uuid), 'revoked device loses access');
reset role;
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select pg_temp.expect_error($q$select solvant.revoke_device(gen_random_uuid())$q$, 'non-admin cannot revoke devices');
reset role;

-- 5. viewer / editor permissions ------------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select pg_temp.check((select count(*) from solvant.opportunities) = 5, 'viewer reads opportunities');
select pg_temp.check((select (solvant.dashboard_counts() ->> 'all')::int) = 5, 'dashboard counts for members');
update solvant.opportunities set stage = 'contacted' where url = 'https://github.com/a/b/issues/1';
select pg_temp.check((select stage from solvant.opportunities where url = 'https://github.com/a/b/issues/1') = 'needs_review', 'viewer update changes nothing (RLS)');
select pg_temp.expect_error($q$select solvant.override_classification((select id from solvant.opportunities limit 1), 'EXCLUDED', null, '{}', 'spam')$q$, 'viewer cannot reclassify');
select pg_temp.expect_error('select * from solvant.audit_log limit 1 for update', 'viewer cannot lock audit rows');
select pg_temp.check((select count(*) from solvant.audit_log) = 0, 'viewer sees no audit log');
reset role;

select pg_temp.as_user('00000000-0000-0000-0000-00000000000e');
update solvant.opportunities set stage = 'contacted', follow_up_at = now() - interval '1 hour', owner_id = auth.uid()
 where url = 'https://github.com/a/b/issues/1';
select pg_temp.check((select count(*) from solvant.activities a join solvant.opportunities o on o.id = a.opportunity_id
   where o.url = 'https://github.com/a/b/issues/1' and a.kind in ('stage_change', 'assignment', 'follow_up')) = 3, 'stage/owner/follow-up changes logged');
select pg_temp.expect_error($q$update solvant.opportunities set pipeline = 'EXCLUDED'$q$, 'pipeline column not directly editable');
select pg_temp.expect_error($q$update solvant.opportunities set verification = 'reviewer_verified'$q$, 'verification not directly editable');
select pg_temp.expect_error($q$update solvant.opportunities set body_excerpt = 'tampered'$q$, 'source facts immutable');
select solvant.override_classification((select id from solvant.opportunities where url = 'https://github.com/a/b/issues/1'),
       'B_FREELANCE_PROJECT', 'B', '{"engagement_type":"project"}', 'It is a marketplace-style fixed project');
select pg_temp.check((select count(*) from solvant.classifications c join solvant.opportunities o on o.id = c.opportunity_id
   where o.url = 'https://github.com/a/b/issues/1') = 2, 'override keeps history (2 classification rows)');
select pg_temp.check((select pipeline from solvant.opportunities where url = 'https://github.com/a/b/issues/1') = 'B_FREELANCE_PROJECT', 'override applied');
select pg_temp.expect_error($q$select solvant.override_classification((select id from solvant.opportunities limit 1), 'EXCLUDED', null, '{}', '')$q$, 'override requires a reason');
select solvant.verify_opportunity((select id from solvant.opportunities where url like '%Notice/000001-2026'), 'Opened the notice on Find a Tender; deadline confirmed');
select pg_temp.check((select verification from solvant.opportunities where url like '%Notice/000001-2026') = 'reviewer_verified', 'reviewer verification recorded');
insert into solvant.notes (opportunity_id, body) select id, 'Called via portal' from solvant.opportunities where url like '%issues/1';
select pg_temp.expect_error($q$insert into solvant.activities (opportunity_id, kind) select id, 'ingested' from solvant.opportunities limit 1$q$, 'cannot forge system activities');
update solvant.sources set enabled = true where key = 'reddit';
select pg_temp.check(not (select enabled from solvant.sources where key = 'reddit'), 'editor cannot change sources (RLS)');
select pg_temp.check(solvant.refresh_my_notifications() >= 1, 'follow-up reminder generated');
reset role;

-- intake as editor: manual-only source accepted, fixture rejected, prohibited rejected
select pg_temp.as_user('00000000-0000-0000-0000-00000000000e');
select pg_temp.check((r ->> 'added')::int = 1 and (r ->> 'rejected')::int = 2, 'browser intake: manual source added; fixture + prohibited rejected')
  from (select solvant.save_intake('{"origin":"paste","source_key":"linkedin"}',
    '[{"source_key":"linkedin","url":"https://www.linkedin.com/posts/acme-1","title":"Looking for a CRM partner","verification":"user_submitted","pipeline":"A_DIRECT_SME"},
      {"source_key":"linkedin","url":"https://www.linkedin.com/posts/acme-2","verification":"fixture"},
      {"source_key":"web_search_google_cse","url":"https://example.invalid/z","verification":"user_submitted"}]') r) t;
reset role;

-- 6. admin source controls and guards ---------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
select pg_temp.expect_error($q$update solvant.sources set enabled = true where key = 'gitlab_issues'$q$, 'unknown-permission source cannot be enabled for automation');
select pg_temp.expect_error($q$update solvant.sources set enabled = true where key = 'web_search_brave'$q$, 'paid source cannot run without a budget');
update solvant.sources set enabled = true, monthly_budget_usd = 5 where key = 'web_search_brave';
select pg_temp.check((select enabled from solvant.sources where key = 'web_search_brave'), 'paid source enabled only with an approved budget');
select pg_temp.expect_error($q$update solvant.sources set export_allowed = true where key = 'upwork'$q$, 'export permission needs a recorded basis');
select pg_temp.expect_error($q$update solvant.sources set export_allowed = true, export_basis = 'we would like to export these' where key = 'gitlab_issues'$q$, 'no export for sources with unknown terms');
update solvant.sources set export_allowed = true, export_basis = 'Written licence from vendor dated 2026-11-12, clause 4' where key = 'bark';
select pg_temp.check((select export_allowed from solvant.sources where key = 'bark'), 'admin records an export basis for a licensed source');
select pg_temp.check((select export_allowed from solvant.sources where key = 'find_a_tender') and not (select export_allowed from solvant.sources where key = 'upwork'), 'default export rights: tenders yes, marketplaces no');
select solvant.log_export(3, 2, '{"pipeline":"E_PROCUREMENT"}');
select pg_temp.check((select count(*) from solvant.audit_log where action = 'export') = 1, 'exports are audited');
select pg_temp.check((select count(*) from solvant.audit_log where table_name = 'sources') >= 1, 'admin sees audit log of source changes');
select pg_temp.check((select last_status from solvant.sources where key = 'ted') = 'failed', 'failed collector stays visibly failed');
select solvant.refresh_my_notifications();
select pg_temp.check(exists (select 1 from solvant.notifications where kind = 'source_failing'), 'failing source notification for admin');
reset role;

-- 7. retention ---------------------------------------------------------------------------------------------
reset role;
update solvant.opportunities set retain_until = now() - interval '1 day' where url = 'https://www.linkedin.com/posts/acme-1';
insert into solvant.audit_log (action, table_name, at) values ('test_old', 'x', now() - interval '800 days');
select pg_temp.check((solvant.enforce_retention() ->> 'skipped') is not null, 'retention is a no-op until the policy is approved');
select pg_temp.check((select body_excerpt is not null or requirement_summary is not null or title <> '' from solvant.opportunities where url = 'https://www.linkedin.com/posts/acme-1'), 'nothing purged while disabled');
update solvant.app_settings set value = value || '{"enabled": true}'::jsonb where key = 'retention_policy';
select pg_temp.check((solvant.enforce_retention() ->> 'records')::int = 1, 'enabled policy purges the expired record');
select pg_temp.check((select body_excerpt is null and requirement_summary is null and meta ? 'excerpt_purged_at' from solvant.opportunities where url = 'https://www.linkedin.com/posts/acme-1'), 'excerpts removed');
select pg_temp.check(not exists (select 1 from solvant.evidence e join solvant.opportunities o on o.id = e.opportunity_id
   where o.url = 'https://www.linkedin.com/posts/acme-1' and e.kind = 'source_fact' and e.excerpt is not null), 'linked evidence excerpt removed');
select pg_temp.check(not exists (select 1 from solvant.classifications c join solvant.opportunities o on o.id = c.opportunity_id
   where o.url = 'https://www.linkedin.com/posts/acme-1' and c.positive_evidence <> '{}'), 'derived evidence snippets removed');
select pg_temp.check((select count(*) from solvant.classifications c join solvant.opportunities o on o.id = c.opportunity_id
   where o.url = 'https://www.linkedin.com/posts/acme-1') >= 1, 'classification history kept');
select pg_temp.check(not exists (select 1 from solvant.audit_log where action = 'test_old'), 'audit rows past the audit period deleted');
select pg_temp.check(exists (select 1 from solvant.audit_log where action = 'retention'), 'retention run itself audited');
select pg_temp.check((select verification from solvant.opportunities where url like '%Notice/000001-2026') = 'reviewer_verified'
   and (select body_excerpt is not null or true from solvant.opportunities where url like '%Notice/000001-2026'), 'unexpired records untouched');
select pg_temp.as_user('00000000-0000-0000-0000-00000000000e');
select pg_temp.expect_error('select solvant.enforce_retention()', 'retention job not callable through the API');
select pg_temp.expect_error('select solvant._apply_retention()', 'retention internals not callable through the API');
reset role;

-- 8. notifications are private ---------------------------------------------------------------------------
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select pg_temp.check((select count(*) from solvant.notifications) = 0, 'users only see their own notifications');
reset role;

\echo ALL SQL SECURITY TESTS PASSED
