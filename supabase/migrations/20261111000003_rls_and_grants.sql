-- Solvant Signal Engine — row-level security, grants and function privileges.
-- Rules: no anonymous access to any table; being signed in is not enough (membership required);
-- source facts and classifications change only through audited functions; service-role keys never reach browsers.

do $$
declare t text;
begin
  foreach t in array array['members', 'admin_bootstrap', 'app_settings', 'sources', 'discovery_runs', 'search_queries', 'companies',
    'opportunities', 'evidence', 'classifications', 'contact_channels', 'intake_submissions', 'marketplace_alerts', 'duplicate_links',
    'notes', 'activities', 'follow_ups', 'proposals', 'acquisition_costs', 'saved_searches', 'notifications', 'audit_log', 'ingest_tokens'] loop
    execute format('alter table solvant.%I enable row level security', t);
    execute format('alter table solvant.%I force row level security', t);
    execute format('revoke all on table solvant.%I from anon', t);
    execute format('revoke all on table solvant.%I from authenticated', t);
  end loop;
end $$;
revoke all on solvant.source_performance from anon;
revoke all on solvant.source_performance from authenticated;

-- ---------------------------------------------------------------- table privileges for signed-in users (RLS still applies)
grant select on solvant.members, solvant.app_settings, solvant.sources, solvant.discovery_runs, solvant.search_queries, solvant.companies,
  solvant.opportunities, solvant.evidence, solvant.classifications, solvant.contact_channels, solvant.intake_submissions,
  solvant.marketplace_alerts, solvant.duplicate_links, solvant.notes, solvant.activities, solvant.follow_ups, solvant.proposals,
  solvant.acquisition_costs, solvant.saved_searches, solvant.notifications, solvant.audit_log, solvant.source_performance to authenticated;
grant select (id, name, scopes, created_at, last_used_at, revoked_at) on solvant.ingest_tokens to authenticated;

-- Opportunities: sales/CRM fields are editable; source facts, verification and classification are not (use the functions).
grant update (stage, owner_id, follow_up_at, deal_value, deal_currency, won_at, lost_reason, win_reason, company_id, country, org_type,
              organisation, technologies, budget_text, contact_route, acquisition_cost) on solvant.opportunities to authenticated;
grant delete on solvant.opportunities to authenticated;
grant insert, update on solvant.companies to authenticated;
grant insert (opportunity_id, kind, excerpt) on solvant.evidence to authenticated;
grant insert, update, delete on solvant.contact_channels to authenticated;
grant insert, delete on solvant.duplicate_links to authenticated;
grant insert (opportunity_id, body), update (body), delete on solvant.notes to authenticated;
grant insert (opportunity_id, kind, summary, detail, occurred_at) on solvant.activities to authenticated;
grant insert, update, delete on solvant.follow_ups to authenticated;
grant insert, update, delete on solvant.proposals to authenticated;
grant insert, update, delete on solvant.acquisition_costs to authenticated;
grant insert, update, delete on solvant.saved_searches to authenticated;
grant update (read_at) on solvant.notifications to authenticated;
grant update (enabled, schedule_cron, monthly_budget_usd, config, notes, export_allowed, export_basis) on solvant.sources to authenticated;
grant insert, update on solvant.app_settings to authenticated;

-- ---------------------------------------------------------------- policies
-- members
drop policy if exists members_read on solvant.members;
create policy members_read on solvant.members for select to authenticated
  using (user_id = (select auth.uid()) or (select solvant.is_member()));

-- settings
drop policy if exists settings_read on solvant.app_settings;
create policy settings_read on solvant.app_settings for select to authenticated using ((select solvant.is_member()));
drop policy if exists settings_admin_write on solvant.app_settings;
create policy settings_admin_write on solvant.app_settings for insert to authenticated with check ((select solvant.is_admin()));
drop policy if exists settings_admin_update on solvant.app_settings;
create policy settings_admin_update on solvant.app_settings for update to authenticated
  using ((select solvant.is_admin())) with check ((select solvant.is_admin()));

-- sources (admins manage configuration; the table check constraint blocks enabling unknown/prohibited/unbudgeted paid automation)
drop policy if exists sources_read on solvant.sources;
create policy sources_read on solvant.sources for select to authenticated using ((select solvant.is_member()));
drop policy if exists sources_admin_update on solvant.sources;
create policy sources_admin_update on solvant.sources for update to authenticated
  using ((select solvant.is_admin())) with check ((select solvant.is_admin()));

-- read-only for members
do $$
declare t text;
begin
  foreach t in array array['discovery_runs', 'search_queries', 'classifications', 'intake_submissions', 'marketplace_alerts'] loop
    execute format('drop policy if exists %I on solvant.%I', t || '_read', t);
    execute format('create policy %I on solvant.%I for select to authenticated using ((select solvant.is_member()))', t || '_read', t);
  end loop;
end $$;

-- member read + editor write
do $$
declare t text;
begin
  foreach t in array array['companies', 'contact_channels', 'duplicate_links', 'follow_ups', 'proposals'] loop
    execute format('drop policy if exists %I on solvant.%I', t || '_read', t);
    execute format('create policy %I on solvant.%I for select to authenticated using ((select solvant.is_member()))', t || '_read', t);
    execute format('drop policy if exists %I on solvant.%I', t || '_insert', t);
    execute format('create policy %I on solvant.%I for insert to authenticated with check ((select solvant.can_edit()))', t || '_insert', t);
    execute format('drop policy if exists %I on solvant.%I', t || '_update', t);
    execute format('create policy %I on solvant.%I for update to authenticated using ((select solvant.can_edit())) with check ((select solvant.can_edit()))', t || '_update', t);
    execute format('drop policy if exists %I on solvant.%I', t || '_delete', t);
    execute format('create policy %I on solvant.%I for delete to authenticated using ((select solvant.can_edit()))', t || '_delete', t);
  end loop;
end $$;

-- opportunities
drop policy if exists opportunities_read on solvant.opportunities;
create policy opportunities_read on solvant.opportunities for select to authenticated using ((select solvant.is_member()));
drop policy if exists opportunities_update on solvant.opportunities;
create policy opportunities_update on solvant.opportunities for update to authenticated
  using ((select solvant.can_edit())) with check ((select solvant.can_edit()));
drop policy if exists opportunities_delete on solvant.opportunities;
create policy opportunities_delete on solvant.opportunities for delete to authenticated using ((select solvant.is_admin()));

-- evidence: members read; editors add reviewer notes only
drop policy if exists evidence_read on solvant.evidence;
create policy evidence_read on solvant.evidence for select to authenticated using ((select solvant.is_member()));
drop policy if exists evidence_insert on solvant.evidence;
create policy evidence_insert on solvant.evidence for insert to authenticated
  with check ((select solvant.can_edit()) and kind = 'reviewer_note');

-- notes: editors add; authors edit/delete their own
drop policy if exists notes_read on solvant.notes;
create policy notes_read on solvant.notes for select to authenticated using ((select solvant.is_member()));
drop policy if exists notes_insert on solvant.notes;
create policy notes_insert on solvant.notes for insert to authenticated with check ((select solvant.can_edit()));
drop policy if exists notes_update on solvant.notes;
create policy notes_update on solvant.notes for update to authenticated
  using (author_id = (select auth.uid())) with check (author_id = (select auth.uid()));
drop policy if exists notes_delete on solvant.notes;
create policy notes_delete on solvant.notes for delete to authenticated using (author_id = (select auth.uid()) or (select solvant.is_admin()));

-- activities: members read; editors log manual interactions (contact / reply / meeting / proposal / other)
drop policy if exists activities_read on solvant.activities;
create policy activities_read on solvant.activities for select to authenticated using ((select solvant.is_member()));
drop policy if exists activities_insert on solvant.activities;
create policy activities_insert on solvant.activities for insert to authenticated
  with check ((select solvant.can_edit()) and kind in ('contact', 'reply', 'meeting', 'proposal', 'note', 'other'));

-- acquisition costs: members read; admins write
drop policy if exists costs_read on solvant.acquisition_costs;
create policy costs_read on solvant.acquisition_costs for select to authenticated using ((select solvant.is_member()));
drop policy if exists costs_insert on solvant.acquisition_costs;
create policy costs_insert on solvant.acquisition_costs for insert to authenticated with check ((select solvant.is_admin()));
drop policy if exists costs_update on solvant.acquisition_costs;
create policy costs_update on solvant.acquisition_costs for update to authenticated using ((select solvant.is_admin())) with check ((select solvant.is_admin()));
drop policy if exists costs_delete on solvant.acquisition_costs;
create policy costs_delete on solvant.acquisition_costs for delete to authenticated using ((select solvant.is_admin()));

-- saved searches and notifications: own rows only
drop policy if exists saved_searches_own on solvant.saved_searches;
create policy saved_searches_own on solvant.saved_searches for all to authenticated
  using (user_id = (select auth.uid()) and (select solvant.is_member()))
  with check (user_id = (select auth.uid()) and (select solvant.is_member()));
drop policy if exists notifications_own_read on solvant.notifications;
create policy notifications_own_read on solvant.notifications for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists notifications_own_update on solvant.notifications;
create policy notifications_own_update on solvant.notifications for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- audit log and token metadata: admins
drop policy if exists audit_admin_read on solvant.audit_log;
create policy audit_admin_read on solvant.audit_log for select to authenticated using ((select solvant.is_admin()));
drop policy if exists tokens_admin_read on solvant.ingest_tokens;
create policy tokens_admin_read on solvant.ingest_tokens for select to authenticated using ((select solvant.is_admin()));
-- admin_bootstrap: RLS on, no policies => unreachable through the API.

-- ---------------------------------------------------------------- function privileges
do $$
declare f text;
begin
  -- default: nobody can call our functions through the API
  for f in select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'solvant' and p.proname in ('my_role', 'is_member', 'can_edit', 'is_admin', 'setting', 'touch_updated_at',
              'audit_row', 'opportunity_activity', '_ingest_item', '_tally', 'ingest_records', 'save_intake', 'override_classification',
              'verify_opportunity', 'mark_duplicate', 'possible_duplicates', 'claim_admin', 'create_bootstrap_code', 'create_ingest_token',
              'revoke_ingest_token', 'list_members', 'add_member', 'remove_member', 'dashboard_counts', 'refresh_my_notifications',
              'purge_expired_excerpts', 'log_export', 'collector_plan', '_apply_retention', 'enforce_retention') loop
    execute format('revoke all on function %s from public, anon, authenticated', f);
  end loop;
end $$;

grant execute on function solvant.my_role(), solvant.is_member(), solvant.can_edit(), solvant.is_admin() to authenticated;
grant execute on function solvant.save_intake(jsonb, jsonb), solvant.override_classification(uuid, text, text, jsonb, text),
  solvant.verify_opportunity(uuid, text), solvant.mark_duplicate(uuid, uuid), solvant.possible_duplicates(uuid), solvant.claim_admin(text),
  solvant.create_ingest_token(text, text[]), solvant.revoke_ingest_token(uuid), solvant.list_members(),
  solvant.add_member(text, solvant.app_role), solvant.remove_member(uuid), solvant.dashboard_counts(), solvant.refresh_my_notifications(),
  solvant.purge_expired_excerpts(), solvant.log_export(int, int, jsonb) to authenticated;
-- machine ingestion authenticates with its own hashed token (no user session, no service-role key)
grant execute on function solvant.ingest_records(text, jsonb, jsonb), solvant.collector_plan(text) to anon, authenticated;
-- create_bootstrap_code, _ingest_item, setting, triggers: no API access at all.

insert into solvant.schema_migrations (version) values ('20261111000003') on conflict do nothing;
