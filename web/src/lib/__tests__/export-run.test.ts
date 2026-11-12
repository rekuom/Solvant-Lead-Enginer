import { describe, expect, it } from "vitest";
import { runExport, type ExportClient } from "../export-run";

const SOURCES = [
  { key: "find_a_tender", permission_status: "permitted", export_allowed: true, export_basis: "UK Open Government Licence v3.0" },
  { key: "upwork", permission_status: "restricted", export_allowed: false, export_basis: null },
];
const ROWS = [
  { title: "Council CRM tender", url: "https://www.find-tender.service.gov.uk/Notice/000123-2026", source_key: "find_a_tender", verification: "api_verified", meta: {} },
  { title: "Upwork n8n project", url: "https://www.upwork.com/jobs/~01", source_key: "upwork", verification: "user_submitted", meta: {} },
];

/** Fake Supabase client: chainable query builder resolving to fixed data; configurable audit RPC outcome. */
function fake(audit: "ok" | "error" | "throw", calls: string[] = []): ExportClient {
  const builder = (data: unknown) => {
    const b: Record<string, unknown> = {};
    for (const m of ["eq", "neq", "in", "gte", "lte", "ilike", "contains", "textSearch", "order", "range"]) b[m] = () => b;
    b.then = (res: (v: unknown) => unknown) => Promise.resolve({ data, error: null }).then(res);
    return b;
  };
  return {
    from: (t: string) => ({ select: () => builder(t === "sources" ? SOURCES : ROWS) }),
    rpc: (fn: string) => {
      calls.push(fn);
      if (audit === "throw") return Promise.reject(new Error("network down"));
      return Promise.resolve(audit === "ok" ? { data: null, error: null } : { data: null, error: { message: "permission denied" } });
    },
  };
}

describe("CSV export is fail-closed on audit logging", () => {
  it("delivers only permitted rows after a successful audit write", async () => {
    const calls: string[] = [];
    const r = await runExport(fake("ok", calls), "u1", {});
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.csv).toContain("Council CRM tender");
      expect(r.csv).not.toContain("Upwork");
      expect(r.withheld).toBe(1);
    }
    expect(calls).toEqual(["log_export"]);
  });

  it("returns an error and NO csv when the audit RPC reports an error", async () => {
    const r = await runExport(fake("error"), "u1", {});
    expect(r.ok).toBe(false);
    expect(r).not.toHaveProperty("csv");
    if (!r.ok) expect(r.status).toBe(503);
    expect(JSON.stringify(r)).not.toContain("Council CRM tender");
  });

  it("returns an error and NO csv when the audit RPC throws", async () => {
    const r = await runExport(fake("throw"), "u1", {});
    expect(r.ok).toBe(false);
    expect(JSON.stringify(r)).not.toContain("Council CRM tender");
  });
});
