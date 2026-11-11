/** Opportunity list filters: parsed from URL search params, validated, and applied to a Supabase query. */
import { PIPELINES, STAGES } from "./labels";

export type Filters = {
  q?: string;
  pipeline?: string;
  source?: string;
  country?: string;
  tech?: string;
  verification?: string;
  stage?: string;
  priority?: string;
  from?: string;
  to?: string;
  owner?: string;
  sort: "newest" | "rank" | "published" | "follow_up";
  page: number;
  includeExcluded: boolean;
};

export const PAGE_SIZE = 25;
const PIPE_KEYS = new Set<string>(PIPELINES.map((p) => p.key));
const STAGE_KEYS = new Set<string>(STAGES.map((s) => s.key));
const VERIF = new Set(["api_verified", "reviewer_verified", "user_submitted", "licensed_import", "verified", "unverified"]);
const SAFE = /^[\p{L}\p{N} _.\-/+&@']{1,80}$/u;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function clean(v: string | string[] | undefined): string | undefined {
  const s = Array.isArray(v) ? v[0] : v;
  if (!s) return undefined;
  const t = s.trim();
  return t && SAFE.test(t) ? t : undefined;
}

export function parseFilters(sp: Record<string, string | string[] | undefined>): Filters {
  const pipeline = clean(sp.pipeline);
  const stage = clean(sp.stage);
  const verification = clean(sp.verification);
  const priority = clean(sp.priority);
  const sort = clean(sp.sort);
  const from = clean(sp.from);
  const to = clean(sp.to);
  const page = Math.max(1, Math.min(10000, Number.parseInt(clean(sp.page) ?? "1", 10) || 1));
  return {
    q: clean(sp.q),
    pipeline: pipeline && PIPE_KEYS.has(pipeline) ? pipeline : undefined,
    source: clean(sp.source)?.match(/^[a-z0-9_]{2,80}$/) ? clean(sp.source) : undefined,
    country: clean(sp.country),
    tech: clean(sp.tech),
    verification: verification && VERIF.has(verification) ? verification : undefined,
    stage: stage && (STAGE_KEYS.has(stage) || ["open", "awaiting_review", "contacted_plus", "replied_plus", "proposal_plus"].includes(stage)) ? stage : undefined,
    priority: priority && ["A", "B", "C"].includes(priority) ? priority : undefined,
    from: from && DATE.test(from) ? from : undefined,
    to: to && DATE.test(to) ? to : undefined,
    owner: clean(sp.owner) === "me" ? "me" : undefined,
    sort: sort === "rank" || sort === "published" || sort === "follow_up" ? sort : "newest",
    page,
    includeExcluded: clean(sp.excluded) === "1" || pipeline === "EXCLUDED",
  };
}

export const STAGE_GROUPS: Record<string, string[]> = {
  open: ["discovered", "needs_review", "verified", "qualified", "contact_planned", "contacted", "replied", "meeting_scheduled", "proposal_sent", "negotiation"],
  awaiting_review: ["discovered", "needs_review"],
  contacted_plus: ["contacted", "replied", "meeting_scheduled", "proposal_sent", "negotiation", "won"],
  replied_plus: ["replied", "meeting_scheduled", "proposal_sent", "negotiation", "won"],
  proposal_plus: ["proposal_sent", "negotiation", "won"],
};

// Minimal structural type for the parts of the PostgREST builder we use (keeps this module testable without Supabase).
export interface QB {
  eq(c: string, v: unknown): QB;
  neq(c: string, v: unknown): QB;
  in(c: string, v: unknown[]): QB;
  gte(c: string, v: unknown): QB;
  lte(c: string, v: unknown): QB;
  ilike(c: string, v: string): QB;
  contains(c: string, v: unknown[]): QB;
  textSearch(c: string, q: string, o?: { type?: "websearch"; config?: string }): QB;
  order(c: string, o?: { ascending?: boolean; nullsFirst?: boolean }): QB;
  range(a: number, b: number): QB;
}

export function applyFilters<T extends QB>(qb: T, f: Filters, userId?: string): T {
  let q: QB = qb;
  if (f.q) q = q.textSearch("search", f.q, { type: "websearch", config: "simple" });
  if (f.pipeline) q = q.eq("pipeline", f.pipeline);
  else if (!f.includeExcluded) q = q.neq("pipeline", "EXCLUDED");
  if (f.source) q = q.eq("source_key", f.source);
  if (f.country) q = q.ilike("country", f.country.replace(/[%_]/g, ""));
  if (f.tech) q = q.contains("technologies", [f.tech]);
  if (f.verification === "verified") q = q.in("verification", ["api_verified", "reviewer_verified"]);
  else if (f.verification === "unverified") q = q.in("verification", ["user_submitted", "licensed_import", "search_snippet_only"]);
  else if (f.verification) q = q.eq("verification", f.verification);
  if (f.stage) q = STAGE_GROUPS[f.stage] ? q.in("stage", STAGE_GROUPS[f.stage]) : q.eq("stage", f.stage);
  if (f.priority) q = q.eq("priority", f.priority);
  if (f.from) q = q.gte("discovered_at", `${f.from}T00:00:00Z`);
  if (f.to) q = q.lte("discovered_at", `${f.to}T23:59:59Z`);
  if (f.owner === "me" && userId) q = q.eq("owner_id", userId);
  if (f.sort === "rank") q = q.order("rank_score", { ascending: false });
  else if (f.sort === "published") q = q.order("published_at", { ascending: false, nullsFirst: false });
  else if (f.sort === "follow_up") q = q.order("follow_up_at", { ascending: true, nullsFirst: false });
  else q = q.order("discovered_at", { ascending: false });
  const start = (f.page - 1) * PAGE_SIZE;
  return q.range(start, start + PAGE_SIZE - 1) as T;
}

export function toQuery(f: Partial<Filters>, patch: Partial<Filters> = {}): string {
  const m = { ...f, ...patch } as Record<string, unknown>;
  const p = new URLSearchParams();
  for (const k of ["q", "pipeline", "source", "country", "tech", "verification", "stage", "priority", "from", "to", "owner", "sort"]) {
    const v = m[k];
    if (typeof v === "string" && v && !(k === "sort" && v === "newest")) p.set(k, v);
  }
  if (m.includeExcluded && m.pipeline !== "EXCLUDED") p.set("excluded", "1");
  if (typeof m.page === "number" && m.page > 1) p.set("page", String(m.page));
  const s = p.toString();
  return s ? `?${s}` : "";
}
