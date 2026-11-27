"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

type Result = { found: number; accepted: number; added: number; updated: number; rechecked: number; closed_or_removed: number; seconds: number };

/** Runs a quick discovery refresh on the website under this device's own session (no extra credentials):
 *  fresh board projects through the ingest gate, then a re-check of the top saved leads. The daily Claude task still does
 *  the deep qualification and proposal drafts. */
export function RunDiscovery() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setMsg("Reading the project boards… (up to a minute)");
    try {
      const { data } = await createClient().auth.getSession();
      const res = await fetch("/api/engine/discover", { method: "POST", headers: { Authorization: `Bearer ${data.session?.access_token ?? ""}` } });
      const body = (await res.json()) as Partial<Result> & { error?: string };
      if (!res.ok) throw new Error(body.error || "Discovery failed");
      setMsg(`Done in ${body.seconds}s: ${body.found} fresh listings, ${body.added} new leads, ${body.updated} updated, ${body.rechecked} re-checked (${body.closed_or_removed} closed).`);
      router.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Discovery failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button className="btn btn-primary" onClick={run} disabled={busy}>{busy ? "Running…" : "Run discovery"}</button>
      {msg ? <span className="muted max-w-md text-right text-xs" role="status">{msg}</span> : null}
    </div>
  );
}
