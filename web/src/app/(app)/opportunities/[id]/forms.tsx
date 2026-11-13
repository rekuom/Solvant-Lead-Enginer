"use client";
import { useActionState } from "react";
import { overrideClassification, updateDetails, verifyOpportunity } from "../../actions";
import { PIPELINES } from "@/lib/labels";

const INTENTS = ["explicit_hire_request", "quote_request", "recommendation_request", "partner_search", "paid_bounty", "problem_only",
  "employment_or_staffing", "none_or_discussion", "seller_offer", "job_seeker"];
const RELEVANCE = ["relevant", "uncertain", "product_only", "not_relevant"];

function Status({ s }: { s: { error: string; ok?: string } }) {
  if (s.error) return <p className="text-sm text-red-600" role="alert">{s.error}</p>;
  if (s.ok) return <p className="text-sm text-emerald-600" role="status">{s.ok}</p>;
  return null;
}

export function OverrideForm({ id, pipeline, priority }: { id: string; pipeline: string; priority: string | null }) {
  const [s, action, pending] = useActionState(overrideClassification, { error: "" });
  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="id" value={id} />
      <div className="grid grid-cols-2 gap-2">
        <div><label className="label">Pipeline</label>
          <select name="pipeline" defaultValue={pipeline} className="input">{PIPELINES.map((p) => <option key={p.key} value={p.key}>{p.letter} · {p.short}</option>)}</select></div>
        <div><label className="label">Priority</label>
          <select name="priority" defaultValue={priority ?? ""} className="input"><option value="">None</option><option>A</option><option>B</option><option>C</option></select></div>
        <div><label className="label">Buying intent</label>
          <select name="buying_intent" defaultValue="" className="input"><option value="">(keep)</option>{INTENTS.map((i) => <option key={i} value={i}>{i.replace(/_/g, " ")}</option>)}</select></div>
        <div><label className="label">Technical relevance</label>
          <select name="technical_relevance" defaultValue="" className="input"><option value="">(keep)</option>{RELEVANCE.map((i) => <option key={i} value={i}>{i.replace(/_/g, " ")}</option>)}</select></div>
      </div>
      <div><label className="label">Reason (required)</label><input name="reason" className="input" required minLength={3} maxLength={500} placeholder="Why the engine was wrong" /></div>
      <Status s={s} />
      <button className="btn" disabled={pending}>Save correction</button>
      <p className="muted text-xs">The previous classification is kept in the history below.</p>
    </form>
  );
}

export function VerifyForm({ id, url }: { id: string; url: string }) {
  const [s, action, pending] = useActionState(verifyOpportunity, { error: "" });
  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="id" value={id} />
      <p className="text-sm">Open the <a className="text-brand-600 underline" href={url} target="_blank" rel="noopener noreferrer nofollow">original page</a> and confirm what it says.</p>
      <input name="note" className="input" required minLength={3} maxLength={2000} placeholder="What you checked (date, requirement, still open…)" />
      <Status s={s} />
      <button className="btn" disabled={pending}>Mark as verified</button>
    </form>
  );
}

export function DetailsForm({ o, members }: { o: Record<string, any>; members: { user_id: string; email: string | null; display_name: string | null }[] }) {
  const [s, action, pending] = useActionState(updateDetails, { error: "" });
  const local = (v?: string | null) => (v ? new Date(v).toISOString().slice(0, 16) : "");
  return (
    <form action={action} className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      <input type="hidden" name="id" value={o.id} />
      <div><label className="label">Company / buyer</label><input name="organisation" defaultValue={o.organisation ?? ""} className="input" maxLength={200} /></div>
      <div><label className="label">Organisation type</label><input name="org_type" defaultValue={o.org_type ?? ""} className="input" maxLength={80} /></div>
      <div><label className="label">Country</label><input name="country" defaultValue={o.country ?? ""} className="input" maxLength={80} /></div>
      <div><label className="label">Budget (as stated)</label><input name="budget_text" defaultValue={o.budget_text ?? ""} className="input" maxLength={120} /></div>
      <div className="sm:col-span-2"><label className="label">Technologies (comma separated)</label><input name="technologies" defaultValue={(o.technologies ?? []).join(", ")} className="input" /></div>
      <div className="sm:col-span-2"><label className="label">Permitted contact route</label><input name="contact_route" defaultValue={o.contact_route ?? ""} className="input" maxLength={200} /></div>
      <div><label className="label">Owner</label>
        <select name="owner_id" defaultValue={o.owner_id ?? ""} className="input"><option value="">Unassigned</option>
          {members.map((m) => <option key={m.user_id} value={m.user_id}>{m.display_name || m.email || m.user_id.slice(0, 8)}</option>)}</select></div>
      <div><label className="label">Follow-up date</label><input type="datetime-local" name="follow_up_at" defaultValue={local(o.follow_up_at)} className="input" /></div>
      <div><label className="label">Project value</label><input name="deal_value" type="number" min="0" step="1" defaultValue={o.deal_value ?? ""} className="input" /></div>
      <div><label className="label">Currency</label><input name="deal_currency" defaultValue={o.deal_currency ?? "GBP"} className="input" maxLength={3} /></div>
      <div className="sm:col-span-2 flex items-center gap-3"><button className="btn btn-primary" disabled={pending}>Save details</button><Status s={s} /></div>
    </form>
  );
}
