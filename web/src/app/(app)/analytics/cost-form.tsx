"use client";
import { useActionState } from "react";
import { addCost } from "../admin-actions";

export function CostForm({ sources }: { sources: { key: string; name: string }[] }) {
  const [s, action, pending] = useActionState(addCost, { error: "" });
  return (
    <form action={action} className="grid gap-2 sm:grid-cols-6">
      <select name="source_key" className="input sm:col-span-2" defaultValue=""><option value="">General / no source</option>{sources.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}</select>
      <input name="amount" type="number" min="0" step="0.01" required className="input" placeholder="Amount" />
      <input name="currency" defaultValue="GBP" maxLength={3} className="input" />
      <select name="kind" className="input"><option value="lead_purchase">Lead purchase</option><option value="credits">Credits</option><option value="subscription">Subscription</option><option value="api_usage">API usage</option><option value="llm_usage">LLM usage</option><option value="other">Other</option></select>
      <input name="incurred_on" type="date" className="input" />
      <input name="description" className="input sm:col-span-3" placeholder="Description" maxLength={300} />
      <input name="licence_terms" className="input sm:col-span-2" placeholder="Licence / usage terms" maxLength={300} />
      <button className="btn" disabled={pending}>Record cost</button>
      {s.error ? <p className="text-sm text-red-600 sm:col-span-6">{s.error}</p> : s.ok ? <p className="text-sm text-emerald-600 sm:col-span-6">{s.ok}</p> : null}
    </form>
  );
}
