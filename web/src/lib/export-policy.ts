/** Who may leave the platform as a CSV row. Export depends ONLY on the original source's contractual rights and, for
 *  purchased leads, an explicit licence on the record — never on verification status (a lead we verified or imported is
 *  still governed by the source's terms) and never on who entered it. Admins grant source export rights only with a
 *  recorded basis (enforced by the database constraint sources_export_guard). Exports never include excerpts or personal
 *  contact details. */
export type SourcePolicy = { key: string; permission_status: string; export_allowed: boolean; export_basis?: string | null };
export type ExportRecord = { source_key: string; verification: string; meta?: Record<string, unknown> | null };
export type Decision = { allowed: boolean; reason: string };

export function exportDecision(r: ExportRecord, s: SourcePolicy | undefined): Decision {
  if (!s) return { allowed: false, reason: "unknown source" };
  if (s.permission_status === "prohibited" || s.permission_status === "unknown") {
    return { allowed: false, reason: `source terms are ${s.permission_status}` };
  }
  if (!s.export_allowed) return { allowed: false, reason: "the source's terms do not permit export (no export basis recorded)" };
  if (!s.export_basis || s.export_basis.trim().length < 10) return { allowed: false, reason: "export basis not recorded" };
  if (r.verification === "licensed_import" && r.meta?.licence_allows_export !== true) {
    return { allowed: false, reason: "purchased lead: its licence does not explicitly allow export" };
  }
  return { allowed: true, reason: s.export_basis };
}

export const EXPORT_COLUMNS = ["pipeline", "priority", "stage", "title", "url", "source_key", "organisation", "country", "org_type",
  "published_at", "discovered_at", "verification", "buying_intent", "technical_relevance", "engagement_type", "technologies",
  "budget_text", "contact_route", "suggested_service", "deal_value", "follow_up_at"] as const;
