import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { applyFilters, parseFilters } from "@/lib/filters";
import { toCsv } from "@/lib/csv";

const COLS = ["pipeline", "priority", "stage", "title", "url", "source_key", "organisation", "country", "org_type", "published_at",
  "discovered_at", "verification", "buying_intent", "technical_relevance", "engagement_type", "technologies", "budget_text",
  "contact_route", "suggested_service", "deal_value", "follow_up_at"];

/** Exports only records whose source permits export/retention (sources.export_allowed) plus records the team verified or
 *  entered itself. Excerpts are not exported. Private file for the signed-in member; never written to the repository. */
export async function GET(request: NextRequest) {
  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return NextResponse.json({ error: "sign in" }, { status: 401 });
  const { data: role } = await supabase.rpc("my_role");
  if (!role) return NextResponse.json({ error: "members only" }, { status: 403 });
  const sp = Object.fromEntries(request.nextUrl.searchParams.entries());
  const f = { ...parseFilters(sp), page: 1 };
  const { data: sources } = await supabase.from("sources").select("key,export_allowed");
  const allowed = new Set((sources ?? []).filter((s) => s.export_allowed).map((s) => s.key));
  const rows: Record<string, unknown>[] = [];
  let skipped = 0;
  for (let page = 1; page <= 40; page++) {
    const q = applyFilters(supabase.from("opportunities").select(COLS.join(",")) as never, { ...f, page }, auth.user.id) as unknown as
      Promise<{ data: Record<string, unknown>[] | null }>;
    const { data } = await q;
    if (!data?.length) break;
    for (const r of data) {
      const own = r.verification === "reviewer_verified" || ["user_submitted", "licensed_import"].includes(String(r.verification));
      if (allowed.has(String(r.source_key)) || own) rows.push(r);
      else skipped++;
    }
    if (data.length < 25) break;
  }
  const csv = toCsv(rows, COLS);
  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="solvant-opportunities-${new Date().toISOString().slice(0, 10)}.csv"`,
      "Cache-Control": "no-store",
      "X-Export-Skipped-Restricted": String(skipped),
    },
  });
}
