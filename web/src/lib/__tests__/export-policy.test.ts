import { describe, expect, it } from "vitest";
import { exportDecision, EXPORT_COLUMNS } from "../export-policy";

const tenders = { key: "find_a_tender", permission_status: "permitted", export_allowed: true, export_basis: "UK Open Government Licence v3.0" };
const upwork = { key: "upwork", permission_status: "restricted", export_allowed: false, export_basis: null };
const linkedin = { key: "linkedin", permission_status: "manual_only", export_allowed: false, export_basis: null };
const bark = { key: "bark", permission_status: "licensed", export_allowed: true, export_basis: "Vendor licence dated 2026-11-12, clause 4" };

describe("export permissions", () => {
  it("allows public procurement notices under their open licence", () => {
    expect(exportDecision({ source_key: "find_a_tender", verification: "api_verified" }, tenders).allowed).toBe(true);
  });

  it("never exports restricted marketplace leads, even when verified or entered by the team", () => {
    for (const verification of ["user_submitted", "reviewer_verified", "api_verified"]) {
      expect(exportDecision({ source_key: "upwork", verification }, upwork).allowed).toBe(false);
    }
    expect(exportDecision({ source_key: "linkedin", verification: "reviewer_verified" }, linkedin).allowed).toBe(false);
  });

  it("licensed leads need BOTH a source export basis and an explicit per-record licence", () => {
    expect(exportDecision({ source_key: "bark", verification: "licensed_import" }, bark).allowed).toBe(false);
    expect(exportDecision({ source_key: "bark", verification: "licensed_import", meta: { licence_allows_export: "yes" } }, bark).allowed).toBe(false);
    expect(exportDecision({ source_key: "bark", verification: "licensed_import", meta: { licence_allows_export: true } }, bark).allowed).toBe(true);
    const noBasis = { ...bark, export_allowed: false };
    expect(exportDecision({ source_key: "bark", verification: "licensed_import", meta: { licence_allows_export: true } }, noBasis).allowed).toBe(false);
  });

  it("refuses unknown/prohibited sources and missing bases", () => {
    expect(exportDecision({ source_key: "x", verification: "api_verified" }, undefined).allowed).toBe(false);
    expect(exportDecision({ source_key: "g", verification: "api_verified" }, { key: "g", permission_status: "unknown", export_allowed: true, export_basis: "long enough basis" }).allowed).toBe(false);
    expect(exportDecision({ source_key: "g", verification: "api_verified" }, { ...tenders, export_basis: "" }).allowed).toBe(false);
  });

  it("exports no excerpts or contact details", () => {
    for (const c of ["body_excerpt", "requirement_summary", "meta", "author_ref", "stated_role"]) {
      expect(EXPORT_COLUMNS as readonly string[]).not.toContain(c);
    }
  });
});
