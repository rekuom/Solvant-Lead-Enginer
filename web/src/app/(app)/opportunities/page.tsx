import Link from "next/link";
import { requireMember, canEdit } from "@/lib/session";
import { applyFilters, parseFilters, toQuery, PAGE_SIZE } from "@/lib/filters";
import { PIPELINES, PIPELINE_BY_KEY, STAGES, STAGE_LABEL, VERIFICATION, humanize, INTENT_TONE } from "@/lib/labels";
import { Badge, Empty, PageHeader, fmtDate } from "@/components/ui";
import { bulkUpdate, saveSearch } from "../actions";

export const metadata = { title: "Opportunities" };
const COLS = "id,title,url,source_key,organisation,country,org_type,published_at,discovered_at,technologies,budget_text,verification,buying_intent,technical_relevance,contact_route,priority,pipeline,stage,owner_id,follow_up_at,duplicate_of,requirement_summary";

export default async function Opportunities({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { supabase, user, role } = await requireMember();
  const f = parseFilters(await searchParams);
  const base = supabase.from("opportunities").select(COLS, { count: "exact" });
  const [{ data: rows, count, error }, { data: sources }] = await Promise.all([
    applyFilters(base as never, f, user.id) as unknown as Promise<{ data: Record<string, any>[] | null; count: number | null; error: { message: string } | null }>,
    supabase.from("sources").select("key,name").order("name"),
  ]);
  const total = count ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const editable = canEdit(role);
  const exportHref = `/api/export${toQuery(f, { page: 1 })}`;
  return (
    <div>
      <PageHeader title="Opportunities" subtitle={`${total} matching record${total === 1 ? "" : "s"}`}
        actions={<>
          <a href={exportHref} className="btn">Export CSV</a>
          <details className="relative">
            <summary className="btn cursor-pointer list-none">Save search</summary>
            <form action={saveSearch} className="panel absolute right-0 z-10 mt-1 w-64 space-y-2 p-3">
              <input name="name" className="input" placeholder="Name, e.g. UK HubSpot projects" required maxLength={80} />
              <input type="hidden" name="filters" value={JSON.stringify(f)} />
              <button className="btn btn-primary w-full justify-center">Save &amp; notify me of new matches</button>
            </form>
          </details>
        </>} />

      <form className="panel mb-4 grid grid-cols-2 gap-2 p-3 sm:grid-cols-4 lg:grid-cols-8" method="get">
        <input name="q" defaultValue={f.q} placeholder="Keywords…" className="input col-span-2" aria-label="Keywords" />
        <select name="pipeline" defaultValue={f.pipeline ?? ""} className="input" aria-label="Pipeline">
          <option value="">All pipelines</option>
          {PIPELINES.map((p) => <option key={p.key} value={p.key}>{p.letter} · {p.short}</option>)}
        </select>
        <select name="source" defaultValue={f.source ?? ""} className="input" aria-label="Source">
          <option value="">All sources</option>
          {(sources ?? []).map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
        </select>
        <select name="stage" defaultValue={f.stage ?? ""} className="input" aria-label="Stage">
          <option value="">Any stage</option>
          <option value="awaiting_review">Awaiting review</option>
          <option value="open">Open (not won/lost/archived)</option>
          {STAGES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <select name="verification" defaultValue={f.verification ?? ""} className="input" aria-label="Verification">
          <option value="">Any verification</option>
          <option value="verified">Verified</option>
          <option value="unverified">Unverified</option>
          {Object.entries(VERIFICATION).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <input name="country" defaultValue={f.country} placeholder="Country" className="input" aria-label="Country" />
        <input name="tech" defaultValue={f.tech} placeholder="Technology (e.g. HubSpot)" className="input" aria-label="Technology" />
        <select name="priority" defaultValue={f.priority ?? ""} className="input" aria-label="Priority">
          <option value="">Any priority</option><option value="A">A</option><option value="B">B</option><option value="C">C</option>
        </select>
        <input type="date" name="from" defaultValue={f.from} className="input" aria-label="Discovered from" />
        <input type="date" name="to" defaultValue={f.to} className="input" aria-label="Discovered to" />
        <select name="sort" defaultValue={f.sort} className="input" aria-label="Sort">
          <option value="newest">Newest first</option><option value="rank">Highest rank</option>
          <option value="published">Published date</option><option value="follow_up">Follow-up date</option>
        </select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="owner" value="me" defaultChecked={f.owner === "me"} /> Mine</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="excluded" value="1" defaultChecked={f.includeExcluded} /> Include excluded</label>
        <div className="col-span-2 flex gap-2"><button className="btn btn-primary">Apply</button><Link href="/opportunities" className="btn">Reset</Link></div>
      </form>

      {error ? <Empty title="Could not load opportunities">{error.message}</Empty> : !rows?.length ? (
        <Empty title="No opportunities match">Nothing has been discovered or added with these filters yet. Zero is shown honestly — no demo data.</Empty>
      ) : (
        <form action={bulkUpdate}>
          {editable ? (
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
              <span className="muted">Selected:</span>
              <select name="bulk" className="input w-auto" aria-label="Bulk action" defaultValue="">
                <option value="" disabled>Bulk action…</option>
                <option value="assign_me">Assign to me</option>
                {STAGES.map((s) => <option key={s.key} value={s.key}>Move to: {s.label}</option>)}
              </select>
              <button className="btn">Apply to selected</button>
            </div>
          ) : null}
          <div className="panel overflow-x-auto">
            <table className="data">
              <thead><tr>
                {editable ? <th className="w-6"></th> : null}
                <th>Opportunity</th><th>Pipeline</th><th>Stage</th><th>Verification</th><th>Intent / relevance</th>
                <th>Buyer</th><th>Country</th><th>Budget</th><th>Contact route</th><th>Published</th><th>Follow-up</th>
              </tr></thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.id}>
                    {editable ? <td><input type="checkbox" name="ids" value={o.id} aria-label="Select" /></td> : null}
                    <td className="min-w-72">
                      <Link href={`/opportunities/${o.id}`} className="font-medium hover:underline">{o.title || "(untitled)"}</Link>
                      <div className="muted mt-0.5 line-clamp-2 text-xs">{o.requirement_summary}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge>{o.source_key}</Badge>
                        {o.priority ? <Badge tone={o.priority === "A" ? "green" : "gray"}>{o.priority}</Badge> : null}
                        {o.duplicate_of ? <Badge tone="violet">duplicate</Badge> : null}
                        {(o.technologies ?? []).slice(0, 4).map((t: string) => <Badge key={t} tone="blue">{t}</Badge>)}
                      </div>
                    </td>
                    <td><span title={PIPELINE_BY_KEY[o.pipeline]?.label}>{PIPELINE_BY_KEY[o.pipeline]?.letter} · {PIPELINE_BY_KEY[o.pipeline]?.short}</span></td>
                    <td>{STAGE_LABEL[o.stage]}</td>
                    <td><Badge tone={VERIFICATION[o.verification]?.tone}>{VERIFICATION[o.verification]?.label ?? o.verification}</Badge></td>
                    <td><Badge tone={INTENT_TONE(o.buying_intent)}>{humanize(o.buying_intent)}</Badge><div className="muted text-xs">{humanize(o.technical_relevance)}</div></td>
                    <td>{o.organisation ?? "—"}<div className="muted text-xs">{humanize(o.org_type)}</div></td>
                    <td>{o.country ?? "—"}</td>
                    <td>{o.budget_text ?? "—"}</td>
                    <td className="text-xs">{o.contact_route ?? "—"}</td>
                    <td className="whitespace-nowrap">{fmtDate(o.published_at)}</td>
                    <td className="whitespace-nowrap">{fmtDate(o.follow_up_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </form>
      )}

      {pages > 1 ? (
        <nav className="mt-4 flex items-center justify-between text-sm" aria-label="Pagination">
          {f.page > 1 ? <Link className="btn" href={`/opportunities${toQuery(f, { page: f.page - 1 })}`}>← Previous</Link> : <span />}
          <span className="muted">Page {f.page} of {pages}</span>
          {f.page < pages ? <Link className="btn" href={`/opportunities${toQuery(f, { page: f.page + 1 })}`}>Next →</Link> : <span />}
        </nav>
      ) : null}
    </div>
  );
}
