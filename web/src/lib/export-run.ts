/** Builds a permitted CSV export. FAIL-CLOSED: the CSV is returned only after the export has been written to the audit
 *  log; if audit logging fails (or reports an error), no data is delivered. */
import { applyFilters, parseFilters } from "./filters";
import { toCsv } from "./csv";
import { EXPORT_COLUMNS, exportDecision, type SourcePolicy } from "./export-policy";

type Res<T> = { data: T | null; error: { message?: string } | null };
export interface ExportClient {
  from(table: string): { select(cols: string): unknown };
  rpc(fn: string, args: Record<string, unknown>): PromiseLike<Res<unknown>>;
}
export type ExportResult =
  | { ok: true; csv: string; rows: number; withheld: number }
  | { ok: false; status: number; error: string };

export async function runExport(client: ExportClient, userId: string, sp: Record<string, string>): Promise<ExportResult> {
  const f = { ...parseFilters(sp), page: 1 };
  const src = (await (client.from("sources").select("key,permission_status,export_allowed,export_basis") as PromiseLike<Res<SourcePolicy[]>>));
  if (src.error || !src.data) return { ok: false, status: 503, error: "Could not load source export permissions; nothing exported." };
  const policy = new Map<string, SourcePolicy>(src.data.map((s) => [s.key, s]));
  const rows: Record<string, unknown>[] = [];
  let withheld = 0;
  for (let page = 1; page <= 40; page++) {
    const q = applyFilters(client.from("opportunities").select([...EXPORT_COLUMNS, "meta"].join(",")) as never, { ...f, page }, userId) as unknown as
      PromiseLike<Res<Record<string, unknown>[]>>;
    const { data, error } = await q;
    if (error) return { ok: false, status: 503, error: "Could not read opportunities; nothing exported." };
    if (!data?.length) break;
    for (const r of data) {
      const d = exportDecision({ source_key: String(r.source_key), verification: String(r.verification), meta: r.meta as Record<string, unknown> },
        policy.get(String(r.source_key)));
      if (d.allowed) rows.push(r);
      else withheld++;
    }
    if (data.length < 25) break;
  }
  let audit: Res<unknown>;
  try {
    audit = await client.rpc("log_export", { p_rows: rows.length, p_withheld: withheld, p_filters: sp });
  } catch {
    audit = { data: null, error: { message: "audit call failed" } };
  }
  if (!audit || audit.error) {
    return { ok: false, status: 503, error: "The export could not be recorded in the audit log, so no data was exported. Try again later." };
  }
  return { ok: true, csv: toCsv(rows, [...EXPORT_COLUMNS]), rows: rows.length, withheld };
}
