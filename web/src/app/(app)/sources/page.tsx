import Link from "next/link";
import { requireMember } from "@/lib/session";
import { Badge, PageHeader, fmtDate } from "@/components/ui";
import { humanize, type Tone } from "@/lib/labels";
import { SourceForm } from "./source-form";

export const metadata = { title: "Sources" };

const PERM: Record<string, Tone> = { permitted: "green", restricted: "amber", manual_only: "blue", licensed: "violet", unknown: "gray", prohibited: "red" };

function health(s: Record<string, any>): { label: string; tone: Tone } {
  if (!s.automated) return { label: "Manual intake", tone: "blue" };
  if (!s.enabled) return { label: "Disabled", tone: "gray" };
  if (s.last_status === "failed") return { label: "Failing", tone: "red" };
  if (s.last_status === "partial") return { label: "Partly failing", tone: "amber" };
  if (s.last_success_at) return { label: "Working", tone: "green" };
  return { label: "Not run yet", tone: "gray" };
}

export default async function Sources({ searchParams }: { searchParams: Promise<{ family?: string }> }) {
  const { supabase, role } = await requireMember();
  const sp = await searchParams;
  const [{ data: perf }, { data: srcs }, { data: runs }] = await Promise.all([
    supabase.from("source_performance").select("*"),
    supabase.from("sources").select("*").order("family").order("name"),
    supabase.from("discovery_runs").select("source_key,started_at,status,requests,records,failed_requests,est_cost_usd,error_kind")
      .order("started_at", { ascending: false }).limit(60),
  ]);
  const perfBy = Object.fromEntries((perf ?? []).map((p) => [p.source_key, p]));
  const families = Array.from(new Set((srcs ?? []).map((s) => s.family)));
  const list = (srcs ?? []).filter((s) => !sp.family || s.family === sp.family);
  const admin = role === "admin";
  return (
    <div className="space-y-5">
      <PageHeader title="Source control centre"
        subtitle="Every source the engine knows about, its permission status and health. Restricted, unknown and paid sources stay off until their requirements are met." />
      <div className="flex flex-wrap gap-1 text-sm">
        <Link href="/sources" className={`btn ${!sp.family ? "btn-primary" : ""}`}>All ({srcs?.length ?? 0})</Link>
        {families.map((f) => <Link key={f} href={`/sources?family=${f}`} className={`btn ${sp.family === f ? "btn-primary" : ""}`}>{humanize(f)}</Link>)}
      </div>
      <div className="grid gap-3">
        {list.map((s) => {
          const p = perfBy[s.key] ?? {};
          const h = health(s);
          return (
            <div key={s.key} className="panel p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold">{s.name}</h2>
                <Badge tone={h.tone}>{h.label}</Badge>
                <Badge tone={PERM[s.permission_status]} title="Permission status from the source registry">{humanize(s.permission_status)}</Badge>
                <Badge>{humanize(s.collection_mode)}</Badge>
                {s.paid ? <Badge tone="violet">Paid</Badge> : <Badge>Free</Badge>}
                <span className="muted ml-auto text-xs">{humanize(s.family)}</span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4 lg:grid-cols-8">
                <div><dt className="muted text-xs">Last run</dt><dd>{fmtDate(s.last_run_at, true)}</dd></div>
                <div><dt className="muted text-xs">Last success</dt><dd>{fmtDate(s.last_success_at, true)}</dd></div>
                <div><dt className="muted text-xs">Next scheduled</dt><dd>{s.enabled && s.schedule_cron ? <code className="text-xs">{s.schedule_cron}</code> : "—"}</dd></div>
                <div><dt className="muted text-xs">Records</dt><dd><Link className="hover:underline" href={`/opportunities?source=${s.key}&excluded=1`}>{p.records ?? 0}</Link></dd></div>
                <div><dt className="muted text-xs">Opportunities</dt><dd>{(p.records ?? 0) - 0 ? <Link className="hover:underline" href={`/opportunities?source=${s.key}`}>{p.relevant ?? 0} relevant</Link> : 0}</dd></div>
                <div><dt className="muted text-xs">Verified</dt><dd>{p.verified ?? 0}</dd></div>
                <div><dt className="muted text-xs">Won / revenue</dt><dd>{p.won ?? 0} · £{Number(p.revenue ?? 0).toLocaleString("en-GB")}</dd></div>
                <div><dt className="muted text-xs">Cost (est. API / leads)</dt><dd>${Number(p.est_api_cost_usd ?? 0).toFixed(2)} / £{Number(p.acquisition_costs ?? 0).toFixed(0)}</dd></div>
              </dl>
              {s.last_error ? <p className="mt-2 text-sm text-red-600">Last error: {s.last_error}</p> : null}
              <details className="mt-2 text-sm"><summary className="muted cursor-pointer">Permission notes &amp; requirements</summary>
                <p className="mt-1 whitespace-pre-wrap">{s.notes}</p>
                {s.requirements && s.requirements !== "null" ? <p className="muted mt-1 text-xs">Evidence: {s.requirements}</p> : null}
                {s.contact_route ? <p className="mt-1 text-xs">Contact route: {s.contact_route}</p> : null}
              </details>
              {admin ? <SourceForm s={s} /> : null}
            </div>
          );
        })}
      </div>
      <section className="panel p-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide muted">Collection history</h2>
        {runs?.length ? (
          <div className="overflow-x-auto"><table className="data"><thead><tr><th>When</th><th>Source</th><th>Status</th><th>Requests</th><th>Records</th><th>Failed</th><th>Est. cost</th><th>Error</th></tr></thead><tbody>
            {runs.map((r, i) => (
              <tr key={i}><td className="whitespace-nowrap">{fmtDate(r.started_at, true)}</td><td>{r.source_key}</td>
                <td><Badge tone={r.status === "ok" ? "green" : r.status === "failed" ? "red" : r.status === "partial" ? "amber" : "gray"}>{r.status}</Badge></td>
                <td>{r.requests}</td><td>{r.records}</td><td>{r.failed_requests}</td><td>${Number(r.est_cost_usd).toFixed(3)}</td><td className="text-xs">{r.error_kind ?? ""}</td></tr>
            ))}
          </tbody></table></div>
        ) : <p className="muted text-sm">No collection runs recorded yet. Runs appear here once the GitHub Actions collector is connected (Settings → Discovery connection).</p>}
      </section>
    </div>
  );
}
