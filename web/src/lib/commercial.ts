import type { Tone } from "@/lib/labels";

/** What the source itself confirmed when the listing was last re-read (see boards_reader.check_listing). */
export const CHECK_STATUS: Record<string, { label: string; tone: Tone; help: string }> = {
  verified_open: { label: "Open (confirmed by source)", tone: "green", help: "Title, posting date and open status confirmed on the board itself." },
  verified_posted: { label: "Posted (availability not stated)", tone: "blue", help: "Title and posting date confirmed; the source does not state whether it is still open." },
  reachable_unconfirmed: { label: "Page reachable, not confirmed", tone: "amber", help: "The page loads, but title/date/status could not be confirmed. Not verified." },
  closed: { label: "Closed at source", tone: "red", help: "The board shows the project as closed or expired." },
  removed: { label: "Removed at source", tone: "red", help: "The listing no longer exists." },
  unreachable: { label: "Not reachable at last check", tone: "amber", help: "The page could not be loaded at the last check." },
};

export const ACTION: Record<string, { verb: string; tone: Tone }> = {
  submit_proposal: { verb: "Submit proposal", tone: "green" },
  reply_publicly: { verb: "Reply to public request", tone: "green" },
  contact_permitted: { verb: "Contact via permitted channel", tone: "green" },
  research: { verb: "Research further", tone: "amber" },
  none: { verb: "No action", tone: "gray" },
};

type Lead = { pipeline?: string | null; priority?: string | null; source_state?: string | null; stage?: string | null; meta?: Record<string, any> | null };

const LIVE_ACTIONS = new Set(["submit_proposal", "reply_publicly", "contact_permitted"]);
const BUYER = new Set(["A_DIRECT_SME", "B_FREELANCE_PROJECT", "C_AGENCY_PARTNER"]);

/** A live buyer opportunity with a concrete route to the work (what the "Best open opportunities" list shows). */
export function isActionable(o: Lead): boolean {
  const type = o.meta?.action?.type;
  const check = o.meta?.board_check?.status;
  return BUYER.has(o.pipeline ?? "") && (o.priority === "A" || o.priority === "B") && LIVE_ACTIONS.has(type)
    && !["closed", "removed"].includes(o.source_state ?? "") && !["closed", "removed"].includes(check ?? "")
    && !["won", "lost", "archived"].includes(o.stage ?? "");
}

export function nextStep(o: Lead): { verb: string; label: string; tone: Tone } {
  const a = o.meta?.action;
  if (!a?.type) return { verb: "Review", label: o.meta?.next_action ?? "Review the lead and decide the next step", tone: "gray" };
  const k = ACTION[a.type] ?? ACTION.research;
  return { verb: k.verb, label: a.label ?? o.meta?.next_action ?? k.verb, tone: k.tone };
}

export const FUNNEL_STEPS: { key: string; label: string; hint: string }[] = [
  { key: "open_now", label: "Open opportunities", hint: "Buyer opportunities still open at source (last 30 days)" },
  { key: "verified_open", label: "Verified open", hint: "Open status confirmed by the source itself" },
  { key: "proposal_possible", label: "Proposal possible", hint: "Open, priority A/B, with a permitted route (proposal, public reply, invited contact)" },
  { key: "drafts_ready", label: "Drafts ready", hint: "Proposal drafts prepared for review (never sent automatically)" },
  { key: "proposals_submitted", label: "Proposals submitted", hint: "Marked submitted by you" },
  { key: "replies", label: "Replies", hint: "Buyer replied" },
  { key: "meetings", label: "Meetings", hint: "Meeting booked or held" },
  { key: "won", label: "Deals won", hint: "Won" },
];

/** A row of solvant.commercial_candidates(): the same commercial score the daily report uses. */
export type ScoredLead = {
  id: string; title: string | null; url: string; priority: string | null; budget_text: string | null; posted: string | null;
  next_step: string | null; check_status: string | null; bids: number | null; draft_ready: boolean; submitted: boolean;
  status_label: "confirmed_open" | "exists" | "requirement_stated" | string; commercial_score: number; is_new?: boolean; flags?: string[] | null;
};

export const STATUS_LABEL: Record<string, { label: string; tone: Tone; help: string }> = {
  confirmed_open: { label: "Confirmed open", tone: "green", help: "The board itself shows the project as open (re-checked daily)." },
  exists: { label: "Listing exists", tone: "blue", help: "The listing is online but the board does not confirm it is still open." },
  requirement_stated: { label: "Requirement stated", tone: "gray", help: "A public request; the source has no open/closed status." },
};

/** Highest commercial score first (the database already orders; this keeps the UI stable if rows arrive unordered). */
export function byCommercialScore(rows: ScoredLead[]): ScoredLead[] {
  return [...rows].sort((a, b) => (b.commercial_score ?? 0) - (a.commercial_score ?? 0));
}
