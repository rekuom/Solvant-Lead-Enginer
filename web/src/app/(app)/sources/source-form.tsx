"use client";
import { useActionState } from "react";
import { updateSource } from "../admin-actions";

export function SourceForm({ s }: { s: Record<string, any> }) {
  const [st, action, pending] = useActionState(updateSource, { error: "" });
  const blocked = s.permission_status === "unknown" || s.permission_status === "prohibited";
  return (
    <form action={action} className="mt-3 grid gap-2 border-t line pt-3 sm:grid-cols-4">
      <input type="hidden" name="key" value={s.key} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="enabled" defaultChecked={s.enabled} disabled={blocked && s.automated} /> Enabled</label>
      <div><label className="label">Schedule (cron, UTC)</label><input name="schedule_cron" defaultValue={s.schedule_cron ?? ""} className="input" placeholder="17 6 * * *" disabled={!s.automated} /></div>
      <div><label className="label">Monthly budget (USD)</label><input name="monthly_budget_usd" type="number" min="0" step="1" defaultValue={s.monthly_budget_usd ?? 0} className="input" disabled={!s.paid} /></div>
      <div className="flex items-end gap-2"><button className="btn" disabled={pending}>Save</button>
        {st.error ? <span className="text-xs text-red-600">{st.error}</span> : st.ok ? <span className="text-xs text-emerald-600">{st.ok}</span> : null}</div>
      <div><label className="label">Max requests per run</label><input name="max_requests" type="number" min="1" max="30" defaultValue={s.config?.max_requests ?? 20} className="input" disabled={!s.automated} /></div>
      {s.permission_status === "restricted" ? (
        <div className="sm:col-span-3"><label className="label">Restricted-source approval (terms reviewed: who, when, basis)</label>
          <input name="restricted_approval" defaultValue={s.config?.restricted_approval?.basis ?? ""} className="input" maxLength={300} placeholder="Leave empty to keep this source off" /></div>
      ) : <div className="sm:col-span-3" />}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="export_allowed" defaultChecked={s.export_allowed} /> Export permitted</label>
      <div className="sm:col-span-3"><label className="label">Export basis (contract / licence clause — required to export)</label>
        <input name="export_basis" defaultValue={s.export_basis ?? ""} className="input" maxLength={500} /></div>
      <div className="sm:col-span-4"><label className="label">Operator notes</label><input name="notes" defaultValue={s.notes ?? ""} className="input" maxLength={2000} /></div>
    </form>
  );
}
