import { describe, expect, it } from "vitest";
import { applyFilters, parseFilters, toQuery, type QB } from "../filters";
import { csvCell, toCsv } from "../csv";

function recorder() {
  const calls: [string, ...unknown[]][] = [];
  const qb: QB = new Proxy({} as QB, {
    get: (_t, prop: string) => (...args: unknown[]) => {
      calls.push([prop, ...args]);
      return qb;
    },
  });
  return { qb, calls };
}

describe("parseFilters", () => {
  it("accepts valid values and drops unknown or unsafe ones", () => {
    const f = parseFilters({ pipeline: "A_DIRECT_SME", stage: "contacted", verification: "verified", q: "hubspot crm", page: "3", sort: "rank" });
    expect(f).toMatchObject({ pipeline: "A_DIRECT_SME", stage: "contacted", verification: "verified", q: "hubspot crm", page: 3, sort: "rank" });
    const bad = parseFilters({ pipeline: "DROP TABLE", stage: "x", source: "Robert'); --", q: "<script>", page: "-4", from: "2026-13" });
    expect(bad.pipeline).toBeUndefined();
    expect(bad.stage).toBeUndefined();
    expect(bad.source).toBeUndefined();
    expect(bad.q).toBeUndefined();
    expect(bad.page).toBe(1);
  });

  it("hides excluded records unless asked", () => {
    const { qb, calls } = recorder();
    applyFilters(qb, parseFilters({}));
    expect(calls).toContainEqual(["neq", "pipeline", "EXCLUDED"]);
    const r2 = recorder();
    applyFilters(r2.qb, parseFilters({ pipeline: "EXCLUDED" }));
    expect(r2.calls).toContainEqual(["eq", "pipeline", "EXCLUDED"]);
  });

  it("applies grouped stages, verification groups, technology and pagination", () => {
    const { qb, calls } = recorder();
    applyFilters(qb, parseFilters({ stage: "awaiting_review", verification: "unverified", tech: "HubSpot", page: "2" }), "u1");
    expect(calls).toContainEqual(["in", "stage", ["discovered", "needs_review"]]);
    expect(calls).toContainEqual(["in", "verification", ["user_submitted", "licensed_import", "search_snippet_only"]]);
    expect(calls).toContainEqual(["contains", "technologies", ["HubSpot"]]);
    expect(calls).toContainEqual(["range", 25, 49]);
  });

  it("round-trips through the query string", () => {
    const f = parseFilters({ pipeline: "E_PROCUREMENT", q: "crm", page: "2" });
    expect(toQuery(f)).toBe("?q=crm&pipeline=E_PROCUREMENT&page=2");
    expect(toQuery(f, { page: 1 })).toBe("?q=crm&pipeline=E_PROCUREMENT");
  });
});

describe("csv export", () => {
  it("neutralises spreadsheet formula injection and quotes", () => {
    expect(csvCell("=HYPERLINK(\"x\")")).toBe("\"'=HYPERLINK(\"\"x\"\")\"");
    expect(csvCell(["a", "b"])).toBe('"a; b"');
    expect(toCsv([{ a: 1, b: null }], ["a", "b"])).toBe('"a","b"\r\n"1",""\r\n');
  });
});
