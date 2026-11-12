-- OPTIONAL — run only after the data-retention rules are approved (not part of supabase/migrations).
-- 1) Schedules a daily retention job with pg_cron (Supabase extension).
-- 2) The job calls solvant.enforce_retention(), which still does NOTHING until retention_policy.enabled = true.
-- Undo: select cron.unschedule('solvant-retention');
create extension if not exists pg_cron;
select cron.schedule('solvant-retention', '23 3 * * *', $$select solvant.enforce_retention()$$)
 where not exists (select 1 from cron.job where jobname = 'solvant-retention');

-- When the rules are approved, enable them (example; record who approved and when):
-- update solvant.app_settings
--    set value = value || '{"enabled": true, "approved_by": "<name>", "approved_at": "<YYYY-MM-DD>"}'::jsonb, updated_at = now()
--  where key = 'retention_policy';
