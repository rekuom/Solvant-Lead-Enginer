import Link from "next/link";
import { requireMember } from "@/lib/session";
import { PageHeader, StatCard, Section, fmtMoney, fmtDate, Badge } from "@/components/ui";
import { PIPELINES } from "@/lib/labels";
import { FUNNEL_STEPS } from "@/lib/commercial";

export const metadata = { title: "Overview" };

type Counts = Record<string, number>;
type TopLead = {
  id: string; title: string | null; url: string; priority: string | null; budget_text: string | null; posted: string | null;
  next_step: string | null; bids: string | null; status_label: string; commercial_score: number; flags: string[] | null;
  draft_ready: boolean; submitted: boolean;
};
const STATUS: Record<string, { label: string; tone: "green" | "blue" | "amber" }> = {
  confirmed_open: { label: "Open (confirmed by board)", tone: "green" },
  requirement_stated: { label: "Forum request (open status unconfirmed)", tone: "blue" },
  exists: { label: "Listing exists (not confirmed)", tone: "amber" },
};

export default async function Overview() {
  const { supabase } = await requireMember();
  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const [{ data: counts }, { data: failing }, { data: recent }, { data: funnel }, { data: top }] = await Promise.all([
    supabase.rpc("dashboard_counts"),
    supabase.from("sources").select("key,name,last_status,last_error,last_run_at").eq("enabled", true).in("last_status", ["failed", "partial"]),
    supabase.from("opportunities").select("id,title,pipeline,source_key,discovered_at,priority").neq("pipeline", "EXCLUDED")
      .order("discovered_at", { ascending: false }).limit(8),
    supabase.rpc("sales_funnel", { p_days: 30 }),
    // same commercial ranking as the daily report (fit, value, route, competition, open status, freshness), not A/B/C
    supabase.rpc("commercial_top", { p_limit: 5 }),
  ]);
  const f = (funnel ?? {}) as Counts;
  const best = (Array.isArray(top) ? top : []) as TopLead[];
  const c = (counts ?? {}) as Counts;
  const n = (k: string) => Number(c[k] ?? 0);
  return (
    <div className="space-y-6">
      <PageHeader title="Overview" subtitle="Every number is live from the private database and links to the records behind it. Zero means zero."
        actions={<Link href="/intake" className="btn btn-primary">+ Add a lead</Link>} />

      {failing && failing.length > 0 ? (
        <div className="panel border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:bg-red-500/10 dark:text-red-200">
          <b>{failing.length} source(s) not working:</b>{" "}
          {failing.map((s) => s.name).join(", ")} — <Link className="underline" href="/sources">see Sources</Link>
        </div>
      ) : null}

      <h2 className="muted text-xs font-semibold uppercase tracking-wide">Discovery (records found)</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="New today" value={n("today")} href={`/opportunities?from=${today}`} />
        <StatCard label="New this week" value={n("week")} href={`/opportunities?from=${weekAgo}`} />
        <StatCard label="New this month" value={n("month")} href={`/opportunities?from=${monthAgo}`} />
        <StatCard label="All discovered" value={n("all")} href="/opportunities?excluded=1" hint="incl. excluded (audit)" />
        <StatCard label="Verified" value={n("verified")} href="/opportunities?verification=verified&excluded=1" tone="green" />
        <StatCard label="Unverified" value={n("unverified")} href="/opportunities?verification=unverified&excluded=1" />
        <StatCard label="Awaiting review" value={n("awaiting_review")} href="/opportunities?stage=awaiting_review" />
        <StatCard label="Follow-ups due" value={n("follow_ups_due")} href="/follow-ups" />
      </div>

      <Section title="Pipelines">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {PIPELINES.map((p) => (
            <StatCard key={p.key} label={`${p.letter} · ${p.short}`} value={n(p.key)} href={`/opportunities?pipeline=${p.key}`} hint={p.label} />
          ))}
        </div>
      </Section>

      <Section title="Sales funnel (buyer opportunities, last 30 days)">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
          {FUNNEL_STEPS.map((s) => <StatCard key={s.key} label={s.label} value={Number(f[s.key] ?? 0)} href="/opportunities" hint={s.hint} tone={s.key === "won" ? "green" : undefined} />)}
        </div>
        <p className="muted mt-2 text-xs">Discovery counts above are records found; this funnel counts only real buyer opportunities and your actual sales steps.
          Revenue won: {fmtMoney(Number(f.revenue ?? 0))} · Lead acquisition costs: {fmtMoney(n("acquisition_costs"))}</p>
      </Section>

      <Section title="Today's top 5 to pursue">
        <p className="muted mb-2 text-xs">Ranked by commercial score: technical fit, value, how easy the buyer is to reach, competition, confirmed open status and freshness. Budgets are the buyer's own amount and currency. Nothing is sent without you.</p>
        {best.length ? (
          <ol className="divide-y line">
            {best.map((o, i) => {
              const st = STATUS[o.status_label];
              return (
                <li key={o.id} className="py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="w-5 text-sm font-semibold">{i + 1}.</span>
                    <Badge tone="green" title="Commercial score (0-100)">{o.commercial_score}</Badge>
                    <Link href={`/opportunities/${o.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">{o.title || "(untitled)"}</Link>
                    {st ? <Badge tone={st.tone}>{st.label}</Badge> : null}
                    {o.submitted ? <Badge tone="green">Submitted</Badge> : o.draft_ready ? <Badge tone="violet">Draft ready</Badge> : null}
                  </div>
                  <p className="muted mt-0.5 pl-7 text-xs">
                    {o.budget_text ?? "budget not stated"} · {o.bids ? `${o.bids} offers` : "no visible offers"} · posted {fmtDate(o.posted)}
                    {" · "}<a href={o.url} target="_blank" rel="noopener noreferrer nofollow" className="underline">original ↗</a>
                  </p>
                  <p className="mt-0.5 pl-7 text-xs"><b>Next:</b> {o.next_step ?? "Review the lead"}</p>
                  {o.flags && o.flags.length ? <p className="mt-0.5 pl-7 text-xs text-amber-700 dark:text-amber-300">Check: {o.flags.join(" · ")}</p> : null}
                </li>
              );
            })}
          </ol>
        ) : <p className="muted text-sm">No live opportunities with a permitted route right now.</p>}
      </Section>

      <Section title="Latest opportunities" actions={<Link href="/opportunities" className="text-sm text-brand-600">View all →</Link>}>
        {recent && recent.length ? (
          <ul className="divide-y line">
            {recent.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-2 py-2">
                <Link href={`/opportunities/${o.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">{o.title || "(untitled)"}</Link>
                {o.priority ? <Badge tone={o.priority === "A" ? "green" : "gray"}>Priority {o.priority}</Badge> : null}
                <Badge>{PIPELINES.find((p) => p.key === o.pipeline)?.short}</Badge>
                <span className="muted text-xs">{o.source_key} · {fmtDate(o.discovered_at)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted text-sm">No opportunities yet. Add one from <Link href="/intake" className="underline">Add leads</Link> or connect the discovery collectors in <Link href="/sources" className="underline">Sources</Link>.</p>
        )}
      </Section>
    </div>
  );
}
