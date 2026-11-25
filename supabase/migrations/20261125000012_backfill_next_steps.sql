-- Solvant Signal Engine — give every lead saved before next steps existed one concrete next step (same rules as
-- agent_ingest.next_action), and name the platform on board leads. Adds/replaces only meta.action / meta.next_action.

with src as (
  select o.id,
         case when o.url like 'https://www.codeur.com/%' then 'Codeur'
              when o.url like 'https://www.freelancermap.de/%' then 'freelancermap'
              when o.url like 'https://www.peopleperhour.com/%' then 'PeoplePerHour'
              when o.url like 'https://community.airtable.com/%' then 'the Airtable community'
              when o.url like 'https://community.n8n.io/%' then 'the n8n community forum'
              when o.url like 'https://community.make.com/%' then 'the Make community forum'
              else coalesce(s.name, o.source_key) end as where_name,
         o.pipeline, o.verification, o.source_state, o.meta
    from solvant.opportunities o left join solvant.sources s on s.key = o.source_key
   where not (o.meta ? 'action') or o.meta -> 'action' ->> 'where' = 'the project board'
), act as (
  select id,
         case
           when pipeline = 'EXCLUDED' or coalesce(source_state, '') in ('closed', 'removed')
             then jsonb_build_object('type', 'none', 'label', 'No action: closed or excluded at source')
           when pipeline = 'F_RECRUITMENT_SIGNAL'
             then jsonb_build_object('type', 'research', 'label', 'Employment signal: research the company; consider offering a delivered project instead of a hire')
           when verification = 'search_snippet_only'
             then jsonb_build_object('type', 'research', 'label', 'Research further: open the original, confirm it is a genuine current request before any contact')
           when (meta ->> 'board_listing')::boolean is true or pipeline in ('B_FREELANCE_PROJECT', 'GLOBAL_REVIEW')
             then jsonb_build_object('type', 'submit_proposal', 'label', 'Submit a proposal on ' || where_name || '; contact stays in-platform')
           when pipeline in ('A_DIRECT_SME', 'C_AGENCY_PARTNER', 'D_OPERATIONAL_PAIN')
             then jsonb_build_object('type', 'reply_publicly', 'label', 'Reply publicly in the thread on ' || where_name || ', following its rules on solicitation')
           else jsonb_build_object('type', 'research', 'label', 'Research further before any contact')
         end || jsonb_build_object('where', where_name) as a
    from src
)
update solvant.opportunities o
   set meta = o.meta || jsonb_build_object('action', act.a, 'next_action', act.a ->> 'label')
  from act where act.id = o.id;

insert into solvant.schema_migrations (version) values ('20261125000012') on conflict do nothing;
