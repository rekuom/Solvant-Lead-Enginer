-- The n8n "contractors for ongoing project work" post (an agency subcontracting $300-$900 builds) was classified as a direct
-- SME buyer, so it ranked in the commercial shortlist; its Make copy was already an agency partnership. Reclassify it as
-- C_AGENCY_PARTNER: the previous classification is kept (is_current = false) and the change is logged. A human override is
-- never replaced.
do $$
declare
  v_id uuid;
  v_cur solvant.classifications%rowtype;
begin
  select id into v_id from solvant.opportunities
   where canonical_url = 'https://community.n8n.io/t/looking-for-n8n-contractors-for-ongoing-project-work/325902'
     and pipeline = 'A_DIRECT_SME';
  if v_id is null then return; end if;
  select * into v_cur from solvant.classifications where opportunity_id = v_id and is_current;
  if found and v_cur.engine = 'human' then return; end if;
  if found then
    update solvant.classifications set is_current = false where id = v_cur.id;
    insert into solvant.classifications (opportunity_id, engine, engine_version, pipeline, pipeline_reason, priority, dimensions,
           noise_flags, positive_evidence, negative_evidence, missing_facts, suggested_service, rank_score, confidence)
    values (v_id, 'rules', 'migration-20261126000015', 'C_AGENCY_PARTNER',
            'Agency subcontracting builds at $300-$900 each: partnership, not a direct customer', v_cur.priority, v_cur.dimensions,
            v_cur.noise_flags, v_cur.positive_evidence, v_cur.negative_evidence, v_cur.missing_facts, v_cur.suggested_service,
            v_cur.rank_score, v_cur.confidence);
  end if;
  update solvant.opportunities
     set pipeline = 'C_AGENCY_PARTNER',
         pipeline_reason = 'Agency subcontracting builds at $300-$900 each: partnership, not a direct customer'
   where id = v_id;
  insert into solvant.activities (opportunity_id, kind, summary, detail)
  values (v_id, 'classification_change', 'Reclassified as agency partnership (was direct SME)',
          jsonb_build_object('from', 'A_DIRECT_SME', 'to', 'C_AGENCY_PARTNER'));
end $$;

insert into solvant.schema_migrations (version) values ('20261126000015') on conflict do nothing;
