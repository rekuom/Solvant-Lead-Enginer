-- RECOVERY ONLY: removes the Solvant application schema when a first installation must be undone.
-- It refuses to run if ANY application data exists (opportunities, notes, members beyond none, intake, costs), so it can
-- never delete real records. It touches nothing outside schema `solvant` (pg_trgm in `extensions` is left installed).
-- Normal failures need no recovery: the migrations are applied in ONE transaction and roll back automatically.
do $$
declare
  v_rows bigint := 0;
begin
  if to_regclass('solvant.schema_migrations') is null then
    raise notice 'schema solvant is not an installation of this app (no ledger): nothing done';
    return;
  end if;
  select coalesce((select count(*) from solvant.opportunities), 0) + coalesce((select count(*) from solvant.notes), 0)
       + coalesce((select count(*) from solvant.intake_submissions), 0) + coalesce((select count(*) from solvant.acquisition_costs), 0)
       + coalesce((select count(*) from solvant.members), 0)
    into v_rows;
  if v_rows > 0 then
    raise exception 'refusing: % application row(s) exist. Restore from backup instead of dropping.', v_rows;
  end if;
  drop schema solvant cascade;
  raise notice 'schema solvant removed (it contained no application data)';
end $$;
