-- Solvant Signal Engine — one-time device setup codes and a device registry (replaces the access key in the setup URL).
-- * A setup code is single-use, expires after 15 minutes and is stored only as a SHA-256 hash. Opening /setup/<code> once
--   on a device registers that device; the code is then worthless (no reusable secret in URLs or browser history).
-- * Each device gets its own signed cookie; devices can be revoked individually from Settings.
-- * Codes are created by the owner on an authorised device (Settings → Add a device) or, for the first device, through the
--   discovery token held by the owner's Claude session (at most 3 unused codes at a time).

create table if not exists solvant.devices (
  id           uuid primary key default gen_random_uuid(),
  label        text check (char_length(label) <= 120),
  created_via  text not null check (created_via in ('owner', 'claude_session')),
  created_at   timestamptz not null default now(),
  last_seen_at timestamptz,
  revoked_at   timestamptz
);

create table if not exists solvant.device_setup_codes (
  code_hash   text primary key,
  created_via text not null check (created_via in ('owner', 'claude_session')),
  label       text check (char_length(label) <= 120),
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null,
  used_at     timestamptz,
  device_id   uuid references solvant.devices (id) on delete set null
);

do $$
declare t text;
begin
  foreach t in array array['devices', 'device_setup_codes'] loop
    execute format('alter table solvant.%I enable row level security', t);
    execute format('alter table solvant.%I force row level security', t);
    execute format('revoke all on table solvant.%I from anon, authenticated', t);
    execute format('grant all on table solvant.%I to service_role', t);
  end loop;
end $$;
grant select (id, label, created_via, created_at, last_seen_at, revoked_at) on solvant.devices to authenticated;
drop policy if exists devices_admin_read on solvant.devices;
create policy devices_admin_read on solvant.devices for select to authenticated using ((select solvant.is_admin()));

create or replace function solvant.create_device_setup_code(p_token text default '', p_label text default null)
returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_via text;
  v_code text := replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
begin
  if solvant.is_admin() then
    v_via := 'owner';
  elsif solvant._discovery_token_ok(p_token) then
    v_via := 'claude_session';
    if (select count(*) from solvant.device_setup_codes where used_at is null and expires_at > now()) >= 3 then
      raise exception 'too many unused setup codes' using errcode = '54000';
    end if;
  else
    raise exception 'not allowed' using errcode = '42501';
  end if;
  insert into solvant.device_setup_codes (code_hash, created_via, label, expires_at)
  values (encode(sha256(convert_to(v_code, 'UTF8')), 'hex'), v_via, left(p_label, 120), now() + interval '15 minutes');
  return v_code;
end $$;

-- website server only (service_role): consume a code and register the device
create or replace function solvant.redeem_device_setup_code(p_code text, p_label text default null)
returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_row solvant.device_setup_codes%rowtype;
  v_device uuid;
begin
  select * into v_row from solvant.device_setup_codes
   where code_hash = encode(sha256(convert_to(coalesce(p_code, ''), 'UTF8')), 'hex') for update;
  if not found or v_row.used_at is not null or v_row.expires_at <= now() then
    return null;
  end if;
  insert into solvant.devices (label, created_via) values (coalesce(left(p_label, 120), v_row.label), v_row.created_via) returning id into v_device;
  update solvant.device_setup_codes set used_at = now(), device_id = v_device where code_hash = v_row.code_hash;
  return v_device;
end $$;

-- website server only: is this device still allowed? (also records last use, at most every 10 minutes)
create or replace function solvant.device_active(p_device uuid)
returns boolean
language plpgsql security definer set search_path = '' as $$
declare v_ok boolean;
begin
  update solvant.devices set last_seen_at = now()
   where id = p_device and revoked_at is null and (last_seen_at is null or last_seen_at < now() - interval '10 minutes');
  select revoked_at is null into v_ok from solvant.devices where id = p_device;
  return coalesce(v_ok, false);
end $$;

create or replace function solvant.revoke_device(p_device uuid)
returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not solvant.is_admin() then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  update solvant.devices set revoked_at = now() where id = p_device and revoked_at is null;
end $$;

revoke all on function solvant.create_device_setup_code(text, text) from public;
revoke all on function solvant.redeem_device_setup_code(text, text) from public, anon, authenticated;
revoke all on function solvant.device_active(uuid) from public, anon, authenticated;
revoke all on function solvant.revoke_device(uuid) from public, anon;
grant execute on function solvant.create_device_setup_code(text, text) to anon, authenticated;
grant execute on function solvant.redeem_device_setup_code(text, text), solvant.device_active(uuid) to service_role;
grant execute on function solvant.revoke_device(uuid) to authenticated;

insert into solvant.schema_migrations (version) values ('20261127000019') on conflict do nothing;
