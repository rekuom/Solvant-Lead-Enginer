import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { runExport, type ExportClient } from "@/lib/export-run";

/** Permitted CSV export for signed-in members (rules: lib/export-policy.ts). Fail-closed: the CSV is delivered only after
 *  the export has been recorded in the audit log (lib/export-run.ts). Nothing is stored server-side. */
export async function GET(request: NextRequest) {
  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return NextResponse.json({ error: "sign in" }, { status: 401 });
  const { data: role } = await supabase.rpc("my_role");
  if (!role) return NextResponse.json({ error: "members only" }, { status: 403 });
  const sp = Object.fromEntries(request.nextUrl.searchParams.entries());
  const result = await runExport(supabase as unknown as ExportClient, auth.user.id, sp);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: result.status, headers: { "Cache-Control": "no-store" } });
  }
  return new NextResponse(result.csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="solvant-opportunities-${new Date().toISOString().slice(0, 10)}.csv"`,
      "Cache-Control": "no-store",
      "X-Export-Withheld-Restricted": String(result.withheld),
    },
  });
}
