"use client";
import { useActionState } from "react";
import { addMember, createIngestToken, purgeExpired, saveLlmSettings } from "../admin-actions";

const Msg = ({ s }: { s: { error: string; ok?: string } }) =>
  s.error ? <p className="text-sm text-red-600">{s.error}</p> : s.ok ? <p className="text-sm text-emerald-600">{s.ok}</p> : null;

export function MemberForm() {
  const [s, action, pending] = useActionState(addMember, { error: "" });
  return (
    <form action={action} className="flex flex-wrap items-end gap-2">
      <div className="min-w-56 flex-1"><label className="label">E-mail of an existing account</label><input name="email" type="email" required className="input" /></div>
      <div><label className="label">Role</label><select name="role" className="input"><option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Admin</option></select></div>
      <button className="btn" disabled={pending}>Add / update</button><Msg s={s} />
    </form>
  );
}

export function TokenForm() {
  const [s, action, pending] = useActionState(createIngestToken, { error: "" });
  return (
    <form action={action} className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1"><label className="label">Name</label><input name="name" className="input" defaultValue="github-actions-discovery" maxLength={60} /></div>
        <div><label className="label">Scope</label><select name="scope" className="input"><option value="discovery">Discovery (GitHub Actions)</option><option value="inbound_email">Inbound e-mail webhook</option></select></div>
        <button className="btn" disabled={pending}>Create token</button>
      </div>
      <Msg s={s} />
      {s.token ? <pre className="overflow-x-auto rounded-lg bg-black/80 p-3 text-xs text-white select-all">{s.token}</pre> : null}
    </form>
  );
}

export function LlmForm({ value }: { value: Record<string, any> }) {
  const [s, action, pending] = useActionState(saveLlmSettings, { error: "" });
  return (
    <form action={action} className="grid gap-2 sm:grid-cols-4">
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="enabled" defaultChecked={!!value.enabled} /> Enable LLM assessment</label>
      <input name="provider" className="input" defaultValue={value.provider ?? ""} placeholder="Provider" maxLength={40} />
      <input name="model" className="input" defaultValue={value.model ?? ""} placeholder="Model" maxLength={80} />
      <input name="monthly_budget_usd" type="number" min="0" className="input" defaultValue={value.monthly_budget_usd ?? 0} placeholder="Monthly budget USD" />
      <div className="sm:col-span-4 flex items-center gap-2"><button className="btn" disabled={pending}>Save</button><Msg s={s} /></div>
    </form>
  );
}

export function PurgeForm() {
  const [s, action, pending] = useActionState(purgeExpired, { error: "" });
  return <form action={action} className="flex items-center gap-2"><button className="btn" disabled={pending}>Remove expired excerpts now</button><Msg s={s} /></form>;
}
