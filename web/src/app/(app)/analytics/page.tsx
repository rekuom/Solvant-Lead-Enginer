import Link from "next/link";
import { requireMember } from "@/lib/session";
import { PageHeader, Section, fmtDate, fmtMoney, Empty } from "@/components/ui";
import { CostForm } from "./cost-form";

export const metadata = { title: "Analytics" };
const pct = (a: number, b: number) => (b > 0 ? `${Math.round((100 * a) / b)}%` : "—");

export default async function Analytics() {
  const { supabase, role } = await requireMember();
  const [{ data: perf }, { data: costs }, { data: cls }] = await Promise.all([
    supabase.from("source_performance").select("*"),
    supabase.from("acquisition_costs").select("*").order("incurred_on", { ascending: false }).limit(50),
    supabase.from("classifications").select("engine,created_at").eq("engine", "human").limit(1000),
  ]);
  const rows = (perf ?? []).filter((p) => p.records > 0 || p.runs > 0 || Number(p.acquisition_costs) > 0)
    .sort((a, b) => b.won - a.won || Number(b.revenue) - Number(a.revenue) || b.explicit_buyers - a.explicit_buyers || b.records - a.records);
  const tot = rows.reduce((t, p) => ({
    records: t.records + p.records, relevant: t.relevant + p.relevant, buyers: t.buyers + p.explicit_buyers, contacted: t.contacted + p.contacted,
    won: t.won + p.won, revenue: t.revenue + Number(p.revenue), cost: t.cost + Number(p.acquisition_costs),
  }), { records: 0, relevant: 0, buyers: 0, contacted: 0, won: 0, revenue: 0, cost: 0 });
  return (
    <div className="space-y-5">
      <PageHeader title="Commercial analytics" subtitle="Volume and value side by side. Sources are ordered by real outcomes (deals won, revenue) before volume; low-volume sources are never hidden." />
      <Section title="Funnel by source">
        {!rows.length ? <Empty title="No data yet">Numbers appear as records are collected, reviewed and progressed.</Empty> : (
          <div className="overflow-x-auto"><table className="data">
            <thead><tr><th>Source</th><th>Records</th><th>Relevant</th><th>Explicit buyers</th><th>Contactable</th><th>Reviewed</th><th>Contacted</th><th>Conversations</th><th>Meetings</th><th>Proposals</th><th>Won</th><th>Revenue</th><th>Costs</th><th>Record→won</th><th>Cost/won</th></tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.source_key}>
                  <td><Link href={`/opportunities?source=${p.source_key}&excluded=1`} className="font-medium hover:underline">{p.name}</Link></td>
                  <td>{p.records}</td><td>{p.relevant}</td><td>{p.explicit_buyers}</td><td>{p.contactable}</td><td>{p.reviewed}</td><td>{p.contacted}</td>
                  <td>{p.conversations}</td><td>{p.meetings}</td><td>{p.proposals}</td><td className="font-semibold">{p.won}</td>
                  <td>{fmtMoney(p.revenue)}</td><td>{fmtMoney(p.acquisition_costs)}</td><td>{pct(p.won, p.records)}</td>
                  <td>{p.won > 0 ? fmtMoney(Number(p.acquisition_costs) / p.won) : "—"}</td>
                </tr>
              ))}
              <tr className="font-semibold"><td>Total</td><td>{tot.records}</td><td>{tot.relevant}</td><td>{tot.buyers}</td><td></td><td></td><td>{tot.contacted}</td><td></td><td></td><td></td><td>{tot.won}</td><td>{fmtMoney(tot.revenue)}</td><td>{fmtMoney(tot.cost)}</td><td>{pct(tot.won, tot.records)}</td><td>{tot.won ? fmtMoney(tot.cost / tot.won) : "—"}</td></tr>
            </tbody>
          </table></div>
        )}
        <p className="muted mt-2 text-xs">Small samples: conversion rates are shown, but no source is switched off automatically because of them.</p>
      </Section>
      <Section title="Classifier feedback">
        <p className="text-sm">Human corrections recorded: <b>{cls?.length ?? 0}</b>. Each correction keeps the engine&apos;s original verdict, so accuracy can be measured against real reviews.</p>
      </Section>
      <section id="costs"><Section title="Lead acquisition costs">
        {role === "admin" ? <div className="mb-4"><CostForm sources={(perf ?? []).map((p) => ({ key: p.source_key, name: p.name }))} /></div> : null}
        {costs?.length ? (
          <div className="overflow-x-auto"><table className="data"><thead><tr><th>Date</th><th>Source</th><th>Kind</th><th>Amount</th><th>Description</th><th>Licence</th></tr></thead><tbody>
            {costs.map((c) => <tr key={c.id}><td>{fmtDate(c.incurred_on)}</td><td>{c.source_key ?? "—"}</td><td>{c.kind}</td><td>{fmtMoney(c.amount, c.currency)}</td><td>{c.description}</td><td className="text-xs">{c.licence_terms}</td></tr>)}
          </tbody></table></div>
        ) : <p className="muted text-sm">No costs recorded. Nothing is ever purchased automatically.</p>}
      </Section></section>
    </div>
  );
}
