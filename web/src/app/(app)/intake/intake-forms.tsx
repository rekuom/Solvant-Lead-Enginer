"use client";
import Link from "next/link";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

type Result = { added?: number; updated?: number; duplicates?: number; rejected?: number; rejected_reasons?: Record<string, number>;
  ids?: string[]; errors?: { row?: number; error: string }[]; error?: string };
type Source = { key: string; name: string; permission_status: string; family: string };
const TABS = [
  { k: "paste", label: "Paste a post / brief" },
  { k: "email_file", label: "Upload alert e-mail (.eml)" },
  { k: "csv", label: "Upload CSV" },
  { k: "manual", label: "Detailed form" },
] as const;

async function send(kind: string, payload: Record<string, unknown>): Promise<Result> {
  const supabase = createClient();
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) return { error: "Your session expired — sign in again." };
  const res = await fetch(`/api/engine/intake`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ kind, payload }),
  });
  const body = await res.json().catch(() => ({ error: `Unexpected response (${res.status})` }));
  return res.ok ? body : { error: body.error ?? `Failed (${res.status})` };
}

function readFile(file: File, as: "text" | "b64"): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(r.error);
    r.onload = () => resolve(as === "text" ? String(r.result) : String(r.result).split(",")[1] ?? "");
    as === "text" ? r.readAsText(file) : r.readAsDataURL(file);
  });
}

export function IntakeForms({ sources }: { sources: Source[] }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["k"]>("paste");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const manualSources = sources.filter((s) => s.permission_status !== "prohibited");

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    const f = new FormData(e.currentTarget);
    const val = (k: string) => String(f.get(k) ?? "").trim();
    try {
      let payload: Record<string, unknown> = {};
      if (tab === "paste" || tab === "manual") {
        payload = Object.fromEntries(["source_key", "url", "post_date", "title", "text", "organisation", "stated_role", "country", "budget", "notes", "verified_by"]
          .map((k) => [k, val(k)]));
      } else {
        const file = f.get("file") as File | null;
        if (!file || !file.size) throw new Error("Choose a file first.");
        if (file.size > 2_000_000) throw new Error("Files must be under 2 MB.");
        if (tab === "email_file") {
          if (!/\.(eml|txt)$/i.test(file.name)) throw new Error("Upload the alert saved as an .eml file.");
          payload = { eml_b64: await readFile(file, "b64"), filename: file.name, source_key: val("source_key") || undefined };
        } else {
          if (!/\.csv$/i.test(file.name)) throw new Error("Upload a .csv file.");
          payload = { csv_text: await readFile(file, "text"), filename: file.name, source_key: val("source_key") || undefined };
        }
      }
      setResult(await send(tab, payload));
    } catch (err) {
      setResult({ error: err instanceof Error ? err.message : "Upload failed" });
    } finally {
      setBusy(false);
    }
  }

  const sourceSelect = (required: boolean, filter?: (s: Source) => boolean) => (
    <div>
      <label className="label" htmlFor="source_key">Where was it published?</label>
      <select id="source_key" name="source_key" className="input" required={required} defaultValue="">
        <option value="">{required ? "Choose a source…" : "Detect automatically"}</option>
        {manualSources.filter(filter ?? (() => true)).map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
      </select>
    </div>
  );

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="panel p-4 lg:col-span-2">
        <div className="mb-4 flex flex-wrap gap-1" role="tablist">
          {TABS.map((t) => (
            <button key={t.k} role="tab" aria-selected={tab === t.k} onClick={() => { setTab(t.k); setResult(null); }}
              className={`btn ${tab === t.k ? "btn-primary" : ""}`}>{t.label}</button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="space-y-3" key={tab}>
          {tab === "paste" || tab === "manual" ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {sourceSelect(true)}
                <div><label className="label" htmlFor="url">Original URL (https)</label>
                  <input id="url" name="url" type="url" pattern="https://.*" required className="input" placeholder="https://www.linkedin.com/posts/…" /></div>
              </div>
              <div><label className="label" htmlFor="text">Post / brief text</label>
                <textarea id="text" name="text" required className="input min-h-40" maxLength={20000} placeholder="Paste exactly what the buyer wrote" /></div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div><label className="label" htmlFor="post_date">Publication date</label><input id="post_date" name="post_date" type="date" className="input" /></div>
                <div><label className="label" htmlFor="country">Country (if stated)</label><input id="country" name="country" className="input" maxLength={80} /></div>
                <div><label className="label" htmlFor="budget">Budget (if stated)</label><input id="budget" name="budget" className="input" maxLength={60} /></div>
              </div>
              {tab === "manual" ? (
                <div className="grid gap-3 sm:grid-cols-3">
                  <div><label className="label" htmlFor="title">Title</label><input id="title" name="title" className="input" maxLength={200} /></div>
                  <div><label className="label" htmlFor="organisation">Company (if stated)</label><input id="organisation" name="organisation" className="input" maxLength={200} /></div>
                  <div><label className="label" htmlFor="stated_role">Poster&apos;s stated role</label><input id="stated_role" name="stated_role" className="input" maxLength={60} placeholder="e.g. founder" /></div>
                  <div className="sm:col-span-3"><label className="label" htmlFor="notes">Notes</label><input id="notes" name="notes" className="input" maxLength={300} /></div>
                </div>
              ) : null}
              <div><label className="label" htmlFor="verified_by">I opened the original page and the text is from it (your initials)</label>
                <input id="verified_by" name="verified_by" className="input sm:w-48" maxLength={40} pattern="[A-Za-z0-9 ._\-]{2,40}" placeholder="Leave empty if not checked" /></div>
            </>
          ) : (
            <>
              {tab === "email_file" ? sourceSelect(false, (s) => ["freelance_marketplace", "lead_marketplace"].includes(s.family)) : sourceSelect(false)}
              <div><label className="label" htmlFor="file">{tab === "email_file" ? "Alert e-mail saved as .eml" : "CSV file"}</label>
                <input id="file" name="file" type="file" accept={tab === "email_file" ? ".eml,message/rfc822" : ".csv,text/csv"} className="input" required /></div>
              <p className="muted text-xs">
                {tab === "email_file"
                  ? "Upwork, Freelancer, PeopleperHour, Malt and Fiverr alert formats are recognised; digests are split per project. The file itself is not stored."
                  : "Columns: source_key, url, text (or description), post_date, title, organisation, country, budget, acquisition_cost. Max 1,000 rows. Only leads you are licensed to use."}
              </p>
            </>
          )}
          <button className="btn btn-primary" disabled={busy}>{busy ? "Classifying…" : "Add and classify"}</button>
        </form>
      </div>

      <div className="space-y-4">
        {result ? (
          <div className="panel p-4 text-sm" role="status">
            {result.error ? <p className="text-red-600">{result.error}</p> : (
              <>
                <p className="font-medium">Done: {result.added ?? 0} added · {result.updated ?? 0} already known (updated) · {result.duplicates ?? 0} duplicate · {result.rejected ?? 0} rejected</p>
                {result.rejected_reasons && Object.keys(result.rejected_reasons).length ? (
                  <ul className="muted mt-1 list-disc pl-4 text-xs">{Object.entries(result.rejected_reasons).map(([k, n]) => <li key={k}>{k.replace("rejected:", "")}: {n}</li>)}</ul>
                ) : null}
                {result.errors?.length ? <ul className="mt-1 list-disc pl-4 text-xs text-amber-700">{result.errors.slice(0, 10).map((e, i) => <li key={i}>{e.row !== undefined ? `Row ${e.row + 1}: ` : ""}{e.error}</li>)}</ul> : null}
                {result.ids?.length ? <ul className="mt-2 space-y-1">{result.ids.map((id) => <li key={id}><Link className="text-brand-600 underline" href={`/opportunities/${id}`}>Open record →</Link></li>)}</ul> : null}
              </>
            )}
          </div>
        ) : null}
        <div className="panel p-4 text-sm">
          <h2 className="mb-1 font-semibold">How intake works</h2>
          <ul className="muted list-disc space-y-1 pl-4">
            <li>Everything runs in the private cloud: no software to install.</li>
            <li>Each lead is classified by the same engine as the discovery collectors.</li>
            <li>Duplicates (same URL or same text) are detected automatically.</li>
            <li>Records stay <b>unverified</b> until you confirm them against the original page.</li>
            <li>Only add content you are allowed to use. Platform rules (e.g. in-platform contact only) are attached to the record.</li>
          </ul>
        </div>
        <div className="panel p-4 text-sm">
          <h2 className="mb-1 font-semibold">Forwarding alerts automatically</h2>
          <p className="muted">Needs an inbound-email service (not yet configured). Once set up, alerts forwarded to a private address arrive here automatically. See Settings → Inbound e-mail.</p>
        </div>
      </div>
    </div>
  );
}
