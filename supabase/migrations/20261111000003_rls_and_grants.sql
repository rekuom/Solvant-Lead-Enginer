-- Solvant Signal Engine — row-level security, grants and function privileges.
-- Rules: no anonymous access to any table; being signed in is not enough (membership required);
-- source facts and classifications change only through audited functions; service-role keys never reach browsers.

do $$
declare t text;
begin
  foreach t in array array['members', 'admin_bootstrap', 'app_settings', 'sources', 'discovery_runs', 'search_queries', 'companies',
    'opportunities', 'evidence', 'classifications', 'contact_channels', 'intake_submissions', 'marketplace_alerts', 'duplicate_links',
    'notes', 'activities', 'follow_ups', 'proposals', 'acquisition_costs', 'saved_searches', 'notifications', 'audit_log', 'ingest_tokens'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on table public.%I from anon', t);
    execute format('revoke all on table public.%I from authenticated', t);
  end loop;
end $$;
revoke all on public.source_performance from anon;
revoke all on public.source_performance from authenticated;

-- ---------------------------------------------------------------- table privileges for signed-in users (RLS still applies)
grant select on public.members, public.app_settings, public.sources, public.discovery_runs, public.search_queries, public.companies,
  public.opportunities, public.evidence, public.classifications, public.contact_channels, public.intake_submissions,
  public.marketplace_alerts, public.duplicate_links, public.notes, public.activities, public.follow_ups, public.proposals,
  public.acquisition_costs, public.saved_searches, public.notifications, public.audit_log, public.source_performance to authenticated;
grant select (id, name, scopes, created_at, last_used_at, revoked_at) on public.ingest_tokens to authenticated;

-- Opportunities: sales/CRM fields are editable; source facts, verification and classification are not (use the functions).
grant update (stage, owner_id, follow_up_at, deal_value, deal_currency, won_at, lost_reason, win_reason, company_id, country, org_type,
              organisation, technologies, budget_text, contact_route, acquisition_cost) on public.opportunities to authenticated;
grant delete on public.opportunities to authenticated;
grant insert, update on public.companies to authenticated;
grant insert (opportunity_id, kind, excerpt) on public.evidence to authenticated;
grant insert, update, delete on public.contact_channels to authenticated;
grant insert, delete on public.duplicate_links to authenticated;
grant insert (opportunity_id, body), update (body), delete on public.notes to authenticated;
grant insert (opportunity_id, kind, summary, detail, occurred_at) on public.activities to authenticated;
grant insert, update, delete on public.follow_ups to authenticated;
grant insert, update, delete on public.proposals to authenticated;
grant insert, update, delete on public.acquisition_costs to authenticated;
grant insert, update, delete on public.saved_searches to authenticated;
grant update (read_at) on public.notifications to authenticated;
grant update (enabled, automated, schedule_cron, monthly_budget_usd, config, notes, requirements, export_allowed) on public.sources to authenticated;
grant insert, update on public.app_settings to authenticated;

-- ---------------------------------------------------------------- policies
-- members
drop policy if exists members_read on public.members;
create policy members_read on public.members for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_member()));

-- settings
drop policy if exists settings_read on public.app_settings;
create policy settings_read on public.app_settings for select to authenticated using ((select public.is_member()));
drop policy if exists settings_admin_write on public.app_settings;
create policy settings_admin_write on public.app_settings for insert to authenticated with check ((select public.is_admin()));
drop policy if exists settings_admin_update on public.app_settings;
create policy settings_admin_update on public.app_settings for update to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));

-- sources (admins manage configuration; the table check constraint blocks enabling unknown/prohibited/unbudgeted paid automation)
drop policy if exists sources_read on public.sources;
create policy sources_read on public.sources for select to authenticated using ((select public.is_member()));
drop policy if exists sources_admin_update on public.sources;
create policy sources_admin_update on public.sources for update to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));

-- read-only for members
do $$
declare t text;
begin
  foreach t in array array['discovery_runs', 'search_queries', 'classifications', 'intake_submissions', 'marketplace_alerts'] loop
    execute format('drop policy if exists %I on public.%I', t || '_read', t);
    execute format('create policy %I on public.%I for select to authenticated using ((select public.is_member()))', t || '_read', t);
  end loop;
end $$;

-- member read + editor write
do $$
declare t text;
begin
  foreach t in array array['companies', 'contact_channels', 'duplicate_links', 'follow_ups', 'proposals'] loop
    execute format('drop policy if exists %I on public.%I', t || '_read', t);
    execute format('create policy %I on public.%I for select to authenticated using ((select public.is_member()))', t || '_read', t);
    execute format('drop policy if exists %I on public.%I', t || '_insert', t);
    execute format('create policy %I on public.%I for insert to authenticated with check ((select public.can_edit()))', t || '_insert', t);
    execute format('drop policy if exists %I on public.%I', t || '_update', t);
    execute format('create policy %I on public.%I for update to authenticated using ((select public.can_edit())) with check ((select public.can_edit()))', t || '_update', t);
    execute format('drop policy if exists %I on public.%I', t || '_delete', t);
    execute format('create policy %I on public.%I for delete to authenticated using ((select public.can_edit()))', t || '_delete', t);
  end loop;
end $$;

-- opportunities
drop policy if exists opportunities_read on public.opportunities;
create policy opportunities_read on public.opportunities for select to authenticated using ((select public.is_member()));
drop policy if exists opportunities_update on public.opportunities;
create policy opportunities_update on public.opportunities for update to authenticated
  using ((select public.can_edit())) with check ((select public.can_edit()));
drop policy if exists opportunities_delete on public.opportunities;
create policy opportunities_delete on public.opportunities for delete to authenticated using ((select public.is_admin()));

-- evidence: members read; editors add reviewer notes only
drop policy if exists evidence_read on public.evidence;
create policy evidence_read on public.evidence for select to authenticated using ((select public.is_member()));
drop policy if exists evidence_insert on public.evidence;
create policy evidence_insert on public.evidence for insert to authenticated
  with check ((select public.can_edit()) and kind = 'reviewer_note');

-- notes: editors add; authors edit/delete their own
drop policy if exists notes_read on public.notes;
create policy notes_read on public.notes for select to authenticated using ((select public.is_member()));
drop policy if exists notes_insert on public.notes;
create policy notes_insert on public.notes for insert to authenticated with check ((select public.can_edit()));
drop policy if exists notes_update on public.notes;
create policy notes_update on public.notes for update to authenticated
  using (author_id = (select auth.uid())) with check (author_id = (select auth.uid()));
drop policy if exists notes_delete on public.notes;
create policy notes_delete on public.notes for delete to authenticated using (author_id = (select auth.uid()) or (select public.is_admin()));

-- activities: members read; editors log manual interactions (contact / reply / meeting / proposal / other)
drop policy if exists activities_read on public.activities;
create policy activities_read on public.activities for select to authenticated using ((select public.is_member()));
drop policy if exists activities_insert on public.activities;
create policy activities_insert on public.activities for insert to authenticated
  with check ((select public.can_edit()) and kind in ('contact', 'reply', 'meeting', 'proposal', 'note', 'other'));

-- acquisition costs: members read; admins write
drop policy if exists costs_read on public.acquisition_costs;
create policy costs_read on public.acquisition_costs for select to authenticated using ((select public.is_member()));
drop policy if exists costs_insert on public.acquisition_costs;
create policy costs_insert on public.acquisition_costs for insert to authenticated with check ((select public.is_admin()));
drop policy if exists costs_update on public.acquisition_costs;
create policy costs_update on public.acquisition_costs for update to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));
drop policy if exists costs_delete on public.acquisition_costs;
create policy costs_delete on public.acquisition_costs for delete to authenticated using ((select public.is_admin()));

-- saved searches and notifications: own rows only
drop policy if exists saved_searches_own on public.saved_searches;
create policy saved_searches_own on public.saved_searches for all to authenticated
  using (user_id = (select auth.uid()) and (select public.is_member()))
  with check (user_id = (select auth.uid()) and (select public.is_member()));
drop policy if exists notifications_own_read on public.notifications;
create policy notifications_own_read on public.notifications for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists notifications_own_update on public.notifications;
create policy notifications_own_update on public.notifications for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- audit log and token metadata: admins
drop policy if exists audit_admin_read on public.audit_log;
create policy audit_admin_read on public.audit_log for select to authenticated using ((select public.is_admin()));
drop policy if exists tokens_admin_read on public.ingest_tokens;
create policy tokens_admin_read on public.ingest_tokens for select to authenticated using ((select public.is_admin()));
-- admin_bootstrap: RLS on, no policies => unreachable through the API.

-- ---------------------------------------------------------------- function privileges
do $$
declare f text;
begin
  -- default: nobody can call our functions through the API
  for f in select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('my_role', 'is_member', 'can_edit', 'is_admin', 'setting', 'touch_updated_at',
              'audit_row', 'opportunity_activity', '_ingest_item', '_tally', 'ingest_records', 'save_intake', 'override_classification',
              'verify_opportunity', 'mark_duplicate', 'possible_duplicates', 'claim_admin', 'create_bootstrap_code', 'create_ingest_token',
              'revoke_ingest_token', 'list_members', 'add_member', 'remove_member', 'dashboard_counts', 'refresh_my_notifications',
              'purge_expired_excerpts') loop
    execute format('revoke all on function %s from public, anon, authenticated', f);
  end loop;
end $$;

grant execute on function public.my_role(), public.is_member(), public.can_edit(), public.is_admin() to authenticated;
grant execute on function public.save_intake(jsonb, jsonb), public.override_classification(uuid, text, text, jsonb, text),
  public.verify_opportunity(uuid, text), public.mark_duplicate(uuid, uuid), public.possible_duplicates(uuid), public.claim_admin(text),
  public.create_ingest_token(text, text[]), public.revoke_ingest_token(uuid), public.list_members(),
  public.add_member(text, public.app_role), public.remove_member(uuid), public.dashboard_counts(), public.refresh_my_notifications(),
  public.purge_expired_excerpts() to authenticated;
-- machine ingestion authenticates with its own hashed token (no user session, no service-role key)
grant execute on function public.ingest_records(text, jsonb, jsonb) to anon, authenticated;
-- create_bootstrap_code, _ingest_item, setting, triggers: no API access at all.
