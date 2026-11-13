import Link from "next/link";
import { requireMember } from "@/lib/session";
import { PageHeader, StatCard, Section, fmtMoney, fmtDate, Badge } from "@/components/ui";
import { PIPELINES } from "@/lib/labels";

export const metadata = { title: "Overview" };

type Counts = Record<string, number>;

export default async function Overview() {
  const { supabase } = await requireMember();
  const [{ data: counts }, { data: failing }, { data: recent }] = await Promise.all([
    supabase.rpc("dashboard_counts"),
    supabase.from("sources").select("key,name,last_status,last_error,last_run_at").eq("enabled", true).in("last_status", ["failed", "partial"]),
    supabase.from("opportunities").select("id,title,pipeline,source_key,discovered_at,priority").neq("pipeline", "EXCLUDED")
      .order("discovered_at", { ascending: false }).limit(8),
  ]);
  const c = (counts ?? {}) as Counts;
  const n = (k: string) => Number(c[k] ?? 0);
  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
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

      <Section title="Sales funnel">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard label="Contacted" value={n("contacted")} href="/opportunities?stage=contacted_plus" />
          <StatCard label="Replies received" value={n("replied")} href="/opportunities?stage=replied_plus" />
          <StatCard label="Proposals submitted" value={n("proposals")} href="/opportunities?stage=proposal_plus" />
          <StatCard label="Deals won" value={n("won")} href="/opportunities?stage=won" tone="green" />
          <StatCard label="Revenue (won)" value={fmtMoney(n("revenue"))} href="/analytics" />
          <StatCard label="Lead acquisition costs" value={fmtMoney(n("acquisition_costs"))} href="/analytics#costs" />
        </div>
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
