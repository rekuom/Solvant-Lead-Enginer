-- Solvant Signal Engine — private no-login access and Outlook/Microsoft e-mail outreach.
-- * The website server mints the owner's session for an authorised device with the server-only secret key; it needs to
--   read the owner membership for that (service_role, server-side only).
-- * mail_accounts holds the connected Microsoft mailbox. The OAuth refresh token is stored ENCRYPTED (AES-256-GCM, key
--   derived on the server) and its column is never granted to browser roles; only the server (service_role) reads it.
-- * outreach_emails logs every e-mail actually sent from the connected mailbox, with errors, replies and bounces.

create table if not exists solvant.mail_accounts (
  id                uuid primary key default gen_random_uuid(),
  provider          text not null check (provider in ('microsoft')),
  email             text not null check (char_length(email) <= 320),
  display_name      text check (char_length(display_name) <= 200),
  refresh_token_enc text not null,
  scopes            text,
  active            boolean not null default true,
  connected_at      timestamptz not null default now(),
  last_used_at      timestamptz,
  last_error        text check (char_length(last_error) <= 500),
  unique (provider, email)
);

create table if not exists solvant.outreach_emails (
  id                 uuid primary key default gen_random_uuid(),
  opportunity_id     uuid references solvant.opportunities (id) on delete set null,
  mail_account_id    uuid references solvant.mail_accounts (id) on delete set null,
  proposal_id        uuid references solvant.proposals (id) on delete set null,
  from_address       text check (char_length(from_address) <= 320),
  to_address         text not null check (char_length(to_address) <= 320),
  subject            text not null check (char_length(subject) between 1 and 300),
  body               text not null check (char_length(body) <= 20000),
  status             text not null check (status in ('sent', 'failed')),
  error              text check (char_length(error) <= 500),
  sent_at            timestamptz,
  reply_detected_at  timestamptz,
  bounce_detected_at timestamptz,
  bounce_detail      text check (char_length(bounce_detail) <= 300),
  created_at         timestamptz not null default now()
);
create index if not exists outreach_emails_opp_idx on solvant.outreach_emails (opportunity_id, created_at desc);

do $$
declare t text;
begin
  foreach t in array array['mail_accounts', 'outreach_emails'] loop
    execute format('alter table solvant.%I enable row level security', t);
    execute format('alter table solvant.%I force row level security', t);
    execute format('revoke all on table solvant.%I from anon, authenticated', t);
    execute format('grant all on table solvant.%I to service_role', t);
  end loop;
end $$;

-- members can see the connection status and the sent log, never the token
grant select (id, provider, email, display_name, scopes, active, connected_at, last_used_at, last_error) on solvant.mail_accounts to authenticated;
grant select on solvant.outreach_emails to authenticated;
drop policy if exists mail_accounts_read on solvant.mail_accounts;
create policy mail_accounts_read on solvant.mail_accounts for select to authenticated using ((select solvant.is_member()));
drop policy if exists outreach_emails_read on solvant.outreach_emails;
create policy outreach_emails_read on solvant.outreach_emails for select to authenticated using ((select solvant.is_member()));

-- server-side owner lookup for the authorised device (service_role only)
grant select on solvant.members to service_role;

insert into solvant.schema_migrations (version) values ('20261127000018') on conflict do nothing;
