import Link from "next/link";
import { notFound } from "next/navigation";
import { requireMember, canEdit } from "@/lib/session";
import { Badge, PageHeader, Section, fmtDate, fmtMoney } from "@/components/ui";
import { PIPELINE_BY_KEY, STAGES, STAGE_LABEL, VERIFICATION, humanize, INTENT_TONE } from "@/lib/labels";
import { addContactChannel, addFollowUp, addNote, addProposal, completeFollowUp, logActivity, markDuplicate, setStage } from "../../actions";
import { DetailsForm, OverrideForm, VerifyForm } from "./forms";

type Dim = { value?: string; evidence?: string[]; confidence?: string };
const DIM_LABELS: Record<string, string> = {
  technical_relevance: "Service relevance", buying_intent: "Buying intent", engagement_type: "Engagement type", business_type: "Business type",
  decision_maker_access: "Decision-maker access", contact_permission: "Contact permission", freshness: "Freshness",
  delivery_complexity: "Delivery complexity", location: "Geography", commercial_potential: "Commercial potential", evidence_confidence: "Evidence confidence",
};

export default async function OpportunityDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const { supabase, role } = await requireMember();
  const { data: o } = await supabase.from("opportunities").select("*").eq("id", id).maybeSingle();
  if (!o) notFound();
  const [ev, cls, notes, acts, fus, props, chans, dups, members, src] = await Promise.all([
    supabase.from("evidence").select("*").eq("opportunity_id", id).order("captured_at"),
    supabase.from("classifications").select("*").eq("opportunity_id", id).order("created_at", { ascending: false }),
    supabase.from("notes").select("*").eq("opportunity_id", id).order("created_at", { ascending: false }),
    supabase.from("activities").select("*").eq("opportunity_id", id).order("occurred_at", { ascending: false }).limit(100),
    supabase.from("follow_ups").select("*").eq("opportunity_id", id).order("due_at"),
    supabase.from("proposals").select("*").eq("opportunity_id", id).order("created_at", { ascending: false }),
    supabase.from("contact_channels").select("*").eq("opportunity_id", id),
    supabase.rpc("possible_duplicates", { p_opp: id }),
    supabase.rpc("list_members"),
    supabase.from("sources").select("name,permission_status,notes,contact_route").eq("key", o.source_key).maybeSingle(),
  ]);
  const current = (cls.data ?? []).find((c) => c.is_current);
  const dims = (current?.dimensions ?? {}) as Record<string, Dim>;
  const editable = canEdit(role);
  const v = VERIFICATION[o.verification];
  const p = PIPELINE_BY_KEY[o.pipeline];
  const rules = (o.meta?.marketplace_rules ?? null) as Record<string, unknown> | null;

  return (
    <div className="space-y-5">
      <div className="text-sm"><Link href="/opportunities" className="muted hover:underline">← Opportunities</Link></div>
      <PageHeader title={o.title || "(untitled)"}
        subtitle={<span className="flex flex-wrap items-center gap-1.5">
          <Badge tone={v?.tone} title={v?.help}>{v?.label ?? o.verification}</Badge>
          <Badge>{p?.letter} · {p?.label}</Badge>
          {o.priority ? <Badge tone={o.priority === "A" ? "green" : "gray"}>Priority {o.priority}</Badge> : null}
          <Badge tone="blue">{STAGE_LABEL[o.stage]}</Badge>
          {o.duplicate_of ? <Link href={`/opportunities/${o.duplicate_of}`}><Badge tone="violet">Duplicate — see original</Badge></Link> : null}
        </span>}
        actions={<a href={o.url} target="_blank" rel="noopener noreferrer nofollow" className="btn">Open original ↗</a>} />

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Section title="1–2 · Source evidence (facts as published)">
            <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
              <div><dt className="muted text-xs">Source</dt><dd>{src.data?.name ?? o.source_key}</dd></div>
              <div><dt className="muted text-xs">Published</dt><dd>{fmtDate(o.published_at)}</dd></div>
              <div><dt className="muted text-xs">Discovered</dt><dd>{fmtDate(o.discovered_at)}</dd></div>
              <div><dt className="muted text-xs">State at source</dt><dd>{o.source_state ?? "—"}</dd></div>
              <div><dt className="muted text-xs">Budget (stated)</dt><dd>{o.budget_text ?? "—"}</dd></div>
              <div><dt className="muted text-xs">Via</dt><dd>{o.discovered_via ?? o.origin}</dd></div>
            </dl>
            <blockquote className="whitespace-pre-wrap rounded-lg border-l-4 border-brand-500 bg-brand-50/50 p-3 text-sm dark:bg-brand-500/5">
              {o.body_excerpt || o.requirement_summary || <span className="muted">Excerpt not retained (source terms or retention period). Open the original.</span>}
            </blockquote>
            <p className="muted mt-2 break-all text-xs">Original: <a className="underline" href={o.url} target="_blank" rel="noopener noreferrer nofollow">{o.url}</a></p>
            {(ev.data ?? []).filter((e) => e.kind !== "source_fact").map((e) => (
              <p key={e.id} className="mt-2 text-sm"><Badge tone="green">{humanize(e.kind)}</Badge> {e.excerpt} <span className="muted text-xs">· {fmtDate(e.captured_at, true)}</span></p>
            ))}
          </Section>

          <Section title="3–5 · Engine interpretation (not source fact)">
            <p className="mb-3 text-sm"><b>Why this pipeline:</b> {o.pipeline_reason ?? "—"} <span className="muted">· engine {current?.engine} {current?.engine_version ?? ""} · confidence {current?.confidence ?? "—"}</span></p>
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.entries(DIM_LABELS).map(([k, label]) => {
                const d = dims[k];
                return (
                  <div key={k} className="rounded-lg border line p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="muted text-xs font-medium uppercase">{label}</span>
                      <span className="muted text-[11px]">{d?.confidence ? `${d.confidence} confidence` : ""}</span>
                    </div>
                    <div className="mt-0.5 text-sm font-medium">{k === "buying_intent" ? <Badge tone={INTENT_TONE(d?.value)}>{humanize(d?.value)}</Badge> : humanize(d?.value)}</div>
                    {d?.evidence?.length ? <ul className="muted mt-1 list-disc pl-4 text-xs">{d.evidence.slice(0, 3).map((e, i) => <li key={i}>{e}</li>)}</ul> : null}
                  </div>
                );
              })}
            </div>
            <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
              <div><div className="label">Positive evidence</div><ul className="list-disc pl-4">{(current?.positive_evidence ?? []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></div>
              <div><div className="label">Negative evidence / uncertainty</div><ul className="list-disc pl-4">{[...(current?.negative_evidence ?? [])].map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
                {!current?.negative_evidence?.length ? <span className="muted">None recorded</span> : null}</div>
            </div>
          </Section>

          <Section title="7–8 · Suggested service and commercial considerations">
            <p className="text-sm"><b>Suggested Solvant service:</b> {o.suggested_service ?? "—"}</p>
            <p className="mt-1 text-sm"><b>Delivery complexity:</b> {humanize(o.delivery_complexity)} · <b>Commercial potential:</b> {humanize(o.commercial_potential)}</p>
            {o.meta?.next_action ? <p className="mt-1 text-sm"><b>Suggested next step:</b> {o.meta.next_action}</p> : null}
            {o.acquisition_cost ? <p className="mt-1 text-sm"><b>Acquisition cost:</b> {fmtMoney(o.acquisition_cost)}</p> : null}
          </Section>

          <Section title="10 · Notes and activity">
            {editable ? (
              <div className="mb-4 grid gap-3 sm:grid-cols-2">
                <form action={addNote} className="space-y-2">
                  <input type="hidden" name="id" value={o.id} />
                  <textarea name="body" className="input min-h-20" placeholder="Add a note…" maxLength={5000} required />
                  <button className="btn">Add note</button>
                </form>
                <form action={logActivity} className="space-y-2">
                  <input type="hidden" name="id" value={o.id} />
                  <select name="kind" className="input" defaultValue="contact">
                    <option value="contact">I contacted them</option><option value="reply">They replied</option>
                    <option value="meeting">Meeting held / booked</option><option value="other">Other interaction</option>
                  </select>
                  <input name="summary" className="input" placeholder="Short summary (channel, outcome)" maxLength={500} />
                  <button className="btn">Log interaction</button>
                  <p className="muted text-xs">Logging only — the platform never sends messages.</p>
                </form>
              </div>
            ) : null}
            <ul className="space-y-2 text-sm">
              {[...(notes.data ?? []).map((n) => ({ t: n.created_at, k: "note", s: n.body })),
                ...(acts.data ?? []).map((a) => ({ t: a.occurred_at, k: a.kind, s: a.summary }))]
                .sort((a, b) => (a.t < b.t ? 1 : -1))
                .map((x, i) => (
                  <li key={i} className="flex gap-2"><span className="muted w-36 shrink-0 text-xs">{fmtDate(x.t, true)}</span>
                    <Badge tone={x.k === "note" ? "blue" : "gray"}>{humanize(x.k)}</Badge><span className="whitespace-pre-wrap">{x.s}</span></li>
                ))}
            </ul>
          </Section>

          <Section title="Classification history">
            <ul className="space-y-1 text-sm">
              {(cls.data ?? []).map((c) => (
                <li key={c.id} className={c.is_current ? "font-medium" : "muted"}>
                  {fmtDate(c.created_at, true)} · {c.engine} · {PIPELINE_BY_KEY[c.pipeline]?.short ?? c.pipeline}{c.priority ? ` · ${c.priority}` : ""}
                  {c.reason ? ` — “${c.reason}”` : ""}{c.is_current ? " (current)" : ""}
                </li>
              ))}
            </ul>
          </Section>
        </div>

        <div className="space-y-5">
          <Section title="Sales stage">
            {editable ? (
              <form action={setStage} className="space-y-2">
                <input type="hidden" name="id" value={o.id} />
                <select name="stage" defaultValue={o.stage} className="input">{STAGES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
                <input name="reason" className="input" placeholder="Win/loss reason (when won or lost)" maxLength={300} />
                <input name="value" type="number" min="0" className="input" placeholder="Deal value (when won)" />
                <button className="btn btn-primary w-full justify-center">Update stage</button>
              </form>
            ) : <p className="text-sm">{STAGE_LABEL[o.stage]}</p>}
            {o.won_at ? <p className="mt-2 text-sm">Won {fmtDate(o.won_at)} · {fmtMoney(o.deal_value, o.deal_currency ?? "GBP")}</p> : null}
            {o.lost_reason ? <p className="mt-2 text-sm">Lost: {o.lost_reason}</p> : null}
          </Section>

          <Section title="6 · Buyer details & 9 · contact">
            {editable ? <DetailsForm o={o} members={(members.data ?? []) as never} /> : (
              <p className="text-sm">{o.organisation ?? "Buyer not stated"} · {o.country ?? "—"}</p>
            )}
            <div className="mt-3 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
              <b>Permitted contact:</b> {o.contact_route ?? "not established"}.
              {rules && rules.off_platform_contact === false ? " Platform rules: respond in-platform only; do not move contact off-platform." : ""}
              {src.data?.contact_route ? ` Source guidance: ${src.data.contact_route}` : ""}
            </div>
            <ul className="mt-3 space-y-1 text-sm">
              {(chans.data ?? []).map((c) => <li key={c.id}><Badge>{humanize(c.kind)}</Badge> {c.value} <span className="muted text-xs">({humanize(c.permission)})</span></li>)}
            </ul>
            {editable ? (
              <details className="mt-2"><summary className="cursor-pointer text-sm text-brand-600">Add professional contact route</summary>
                <form action={addContactChannel} className="mt-2 space-y-2">
                  <input type="hidden" name="id" value={o.id} />
                  <select name="kind" className="input">
                    {["in_platform", "reply_in_thread", "procurement_portal", "company_website", "company_contact_form", "business_email", "business_phone", "company_profile"]
                      .map((k) => <option key={k} value={k}>{humanize(k)}</option>)}
                  </select>
                  <input name="value" className="input" placeholder="Company URL / generic business address" maxLength={300} />
                  <select name="permission" className="input">
                    <option value="unknown">Permission unknown</option><option value="invited">Explicitly invited</option>
                    <option value="platform_rules">Per platform rules</option><option value="published_for_business">Published for business enquiries</option>
                    <option value="do_not_contact">Do not contact</option>
                  </select>
                  <p className="muted text-xs">Professional routes only — never personal contact details of private individuals.</p>
                  <button className="btn">Add</button>
                </form>
              </details>
            ) : null}
          </Section>

          <Section title="11 · Follow-ups">
            <ul className="mb-2 space-y-1 text-sm">
              {(fus.data ?? []).map((f) => (
                <li key={f.id} className="flex items-center gap-2">
                  <span className={f.done_at ? "muted line-through" : ""}>{fmtDate(f.due_at, true)} — {f.title}</span>
                  {!f.done_at && editable ? <form action={completeFollowUp}><input type="hidden" name="id" value={f.id} /><button className="text-xs text-brand-600 underline">done</button></form> : null}
                </li>
              ))}
            </ul>
            {editable ? (
              <form action={addFollowUp} className="space-y-2">
                <input type="hidden" name="id" value={o.id} />
                <input name="title" className="input" placeholder="e.g. Check reply on Upwork" maxLength={200} />
                <input name="due_at" type="datetime-local" className="input" required />
                <button className="btn">Add follow-up</button>
              </form>
            ) : null}
          </Section>

          <Section title="Proposals">
            <ul className="mb-2 space-y-1 text-sm">
              {(props.data ?? []).map((pr) => <li key={pr.id}>{pr.title} · {fmtMoney(pr.amount, pr.currency ?? "GBP")} · {pr.status}</li>)}
            </ul>
            {editable ? (
              <form action={addProposal} className="grid grid-cols-2 gap-2">
                <input type="hidden" name="id" value={o.id} />
                <input name="title" className="input col-span-2" placeholder="Proposal title" maxLength={200} required />
                <input name="amount" type="number" min="0" className="input" placeholder="Amount" />
                <input name="currency" className="input" defaultValue="GBP" maxLength={3} />
                <select name="status" className="input col-span-2" defaultValue="sent"><option value="draft">Draft</option><option value="sent">Sent</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option></select>
                <button className="btn col-span-2">Record proposal</button>
              </form>
            ) : null}
          </Section>

          {editable ? (
            <Section title="12 · Verify & correct">
              {o.verification !== "reviewer_verified" && o.verification !== "api_verified" ? <div className="mb-4"><VerifyForm id={o.id} url={o.url} /></div> : null}
              <OverrideForm id={o.id} pipeline={o.pipeline} priority={o.priority} />
            </Section>
          ) : null}

          <Section title="Possible duplicates">
            {(dups.data ?? []).length ? (
              <ul className="space-y-2 text-sm">
                {(dups.data as { id: string; title: string; source_key: string; similarity: number }[]).map((d) => (
                  <li key={d.id} className="flex items-center gap-2">
                    <Link href={`/opportunities/${d.id}`} className="min-w-0 flex-1 truncate hover:underline">{d.title}</Link>
                    <span className="muted text-xs">{Math.round(d.similarity * 100)}%</span>
                    {editable ? <form action={markDuplicate}><input type="hidden" name="id" value={o.id} /><input type="hidden" name="of" value={d.id} /><button className="text-xs text-brand-600 underline">mark dup</button></form> : null}
                  </li>
                ))}
              </ul>
            ) : <p className="muted text-sm">None found.</p>}
          </Section>
        </div>
      </div>
    </div>
  );
}
