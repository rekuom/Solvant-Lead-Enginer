"use client";
import { useActionState } from "react";
import { createDeviceLink, createIngestToken, purgeExpired, saveLlmSettings } from "../admin-actions";

const Msg = ({ s }: { s: { error: string; ok?: string } }) =>
  s.error ? <p className="text-sm text-red-600">{s.error}</p> : s.ok ? <p className="text-sm text-emerald-600">{s.ok}</p> : null;

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

export function AddDeviceForm() {
  const [s, action, pending] = useActionState(createDeviceLink, { error: "" });
  return (
    <form action={action} className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1"><label className="label">Add one of your devices</label><input name="label" className="input" placeholder="e.g. Office PC" maxLength={120} /></div>
        <button className="btn" disabled={pending}>Create one-time link</button>
      </div>
      {s.error ? <p className="text-sm text-red-600">{s.error}</p> : null}
      {s.link ? <div className="text-xs"><p className="muted">Open this link on the new device within 15 minutes. It works once.</p>
        <pre className="overflow-x-auto rounded-lg bg-black/80 p-2 text-white select-all">{s.link}</pre></div> : null}
    </form>
  );
}
