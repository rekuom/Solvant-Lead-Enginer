import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { applyFilters, parseFilters } from "@/lib/filters";
import { toCsv } from "@/lib/csv";
import { EXPORT_COLUMNS, exportDecision, type SourcePolicy } from "@/lib/export-policy";

/** Permitted CSV export for signed-in members. Each row is checked against the source's contractual export rights and,
 *  for purchased leads, the record's explicit licence (see lib/export-policy.ts). Withheld rows are counted, never listed.
 *  Every export is written to the audit log. Nothing is stored server-side. */
export async function GET(request: NextRequest) {
  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return NextResponse.json({ error: "sign in" }, { status: 401 });
  const { data: role } = await supabase.rpc("my_role");
  if (!role) return NextResponse.json({ error: "members only" }, { status: 403 });
  const sp = Object.fromEntries(request.nextUrl.searchParams.entries());
  const f = { ...parseFilters(sp), page: 1 };
  const { data: sources } = await supabase.from("sources").select("key,permission_status,export_allowed,export_basis");
  const policy = new Map<string, SourcePolicy>((sources ?? []).map((s) => [s.key, s as SourcePolicy]));
  const rows: Record<string, unknown>[] = [];
  let withheld = 0;
  for (let page = 1; page <= 40; page++) {
    const q = applyFilters(supabase.from("opportunities").select([...EXPORT_COLUMNS, "meta"].join(",")) as never, { ...f, page }, auth.user.id) as unknown as
      Promise<{ data: Record<string, unknown>[] | null }>;
    const { data } = await q;
    if (!data?.length) break;
    for (const r of data) {
      const d = exportDecision({ source_key: String(r.source_key), verification: String(r.verification), meta: r.meta as Record<string, unknown> }, policy.get(String(r.source_key)));
      if (d.allowed) rows.push(r);
      else withheld++;
    }
    if (data.length < 25) break;
  }
  await supabase.rpc("log_export", { p_rows: rows.length, p_withheld: withheld, p_filters: sp });
  return new NextResponse(toCsv(rows, [...EXPORT_COLUMNS]), {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="solvant-opportunities-${new Date().toISOString().slice(0, 10)}.csv"`,
      "Cache-Control": "no-store",
      "X-Export-Withheld-Restricted": String(withheld),
    },
  });
}
