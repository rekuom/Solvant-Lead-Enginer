export const PIPELINES = [
  { key: "A_DIRECT_SME", letter: "A", label: "Direct SME buyers", short: "Direct SME" },
  { key: "B_FREELANCE_PROJECT", letter: "B", label: "Freelance & project opportunities", short: "Freelance" },
  { key: "C_AGENCY_PARTNER", letter: "C", label: "Agency partnerships", short: "Agency" },
  { key: "D_OPERATIONAL_PAIN", letter: "D", label: "Operational problems & potential demand", short: "Problems" },
  { key: "E_PROCUREMENT", letter: "E", label: "Government & enterprise procurement", short: "Tenders" },
  { key: "F_RECRUITMENT_SIGNAL", letter: "F", label: "Employment & recruitment signals", short: "Recruitment" },
  { key: "G_LICENSED_LEADS", letter: "G", label: "Purchased or licensed leads", short: "Purchased" },
  { key: "H_RESEARCH_UNVERIFIED", letter: "H", label: "Research & unverified", short: "Research" },
  { key: "GLOBAL_REVIEW", letter: "I", label: "Global & exceptional opportunities", short: "Global" },
  { key: "EXCLUDED", letter: "J", label: "Excluded / archived (audit)", short: "Excluded" },
] as const;
export type PipelineKey = (typeof PIPELINES)[number]["key"];
export const PIPELINE_BY_KEY: Record<string, (typeof PIPELINES)[number]> = Object.fromEntries(PIPELINES.map((p) => [p.key, p]));

export const STAGES = [
  { key: "discovered", label: "Discovered" },
  { key: "needs_review", label: "Needs review" },
  { key: "verified", label: "Verified" },
  { key: "qualified", label: "Qualified" },
  { key: "contact_planned", label: "Contact planned" },
  { key: "contacted", label: "Contacted" },
  { key: "replied", label: "Replied" },
  { key: "meeting_scheduled", label: "Meeting scheduled" },
  { key: "proposal_sent", label: "Proposal sent" },
  { key: "negotiation", label: "Negotiation" },
  { key: "won", label: "Won" },
  { key: "lost", label: "Lost" },
  { key: "archived", label: "Archived" },
] as const;
export type StageKey = (typeof STAGES)[number]["key"];
export const STAGE_LABEL: Record<string, string> = Object.fromEntries(STAGES.map((s) => [s.key, s.label]));

export const VERIFICATION: Record<string, { label: string; tone: Tone; help: string }> = {
  api_verified: { label: "Verified (source API)", tone: "green", help: "Fetched from the original publisher's official API" },
  reviewer_verified: { label: "Verified (reviewer)", tone: "green", help: "A team member opened the original page and confirmed it" },
  user_submitted: { label: "Unverified (added by user)", tone: "amber", help: "Content as supplied; open the original URL to verify" },
  licensed_import: { label: "Licensed lead", tone: "blue", help: "From a purchased/licensed lead source; terms of the licence apply" },
  search_snippet_only: { label: "Search snippet only", tone: "gray", help: "Not verified; never treated as a buyer" },
};

export type Tone = "green" | "amber" | "blue" | "gray" | "red" | "violet";

export const humanize = (v?: string | null) =>
  v ? v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bSme\b/, "SME").replace(/\bAi\b/, "AI") : "—";

export const INTENT_TONE = (v?: string | null): Tone =>
  v && ["explicit_hire_request", "quote_request", "recommendation_request", "partner_search", "paid_bounty"].includes(v)
    ? "green"
    : v === "problem_only"
      ? "amber"
      : "gray";
