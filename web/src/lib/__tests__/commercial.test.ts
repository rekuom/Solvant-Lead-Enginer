import { describe, expect, it } from "vitest";
import { isActionable, nextStep, CHECK_STATUS, byCommercialScore, STATUS_LABEL, type ScoredLead } from "../commercial";

const open = { pipeline: "B_FREELANCE_PROJECT", priority: "A", source_state: "open", stage: "discovered",
  meta: { action: { type: "submit_proposal", label: "Submit a proposal on Codeur (12 offers so far)" }, board_check: { status: "verified_open" } } };

describe("commercial actionability", () => {
  it("lists live buyer opportunities with a permitted route", () => {
    expect(isActionable(open)).toBe(true);
    expect(nextStep(open).verb).toBe("Submit proposal");
  });
  it("never lists closed, removed, employment, research-only or finished leads", () => {
    expect(isActionable({ ...open, source_state: "closed" })).toBe(false);
    expect(isActionable({ ...open, meta: { ...open.meta, board_check: { status: "removed" } } })).toBe(false);
    expect(isActionable({ ...open, pipeline: "F_RECRUITMENT_SIGNAL" })).toBe(false);
    expect(isActionable({ ...open, meta: { action: { type: "research" } } })).toBe(false);
    expect(isActionable({ ...open, priority: "C" })).toBe(false);
    expect(isActionable({ ...open, stage: "won" })).toBe(false);
  });
  it("a reachable page is not labelled verified", () => {
    expect(CHECK_STATUS.reachable_unconfirmed.label).not.toMatch(/verified|open \(/i);
    expect(CHECK_STATUS.verified_open.tone).toBe("green");
  });
});

describe("dashboard ranking", () => {
  const row = (id: string, commercial_score: number): ScoredLead => ({ id, title: id, url: "https://x", priority: "B", budget_text: null, posted: null,
    next_step: null, check_status: null, bids: null, draft_ready: false, submitted: false, status_label: "exists", commercial_score });
  it("orders by commercial score, not by priority letter", () => {
    expect(byCommercialScore([row("a", 40), row("b", 81), row("c", 66)]).map((r) => r.id)).toEqual(["b", "c", "a"]);
  });
  it("labels the three status levels honestly", () => {
    expect(STATUS_LABEL.confirmed_open.tone).toBe("green");
    expect(STATUS_LABEL.exists.label).not.toMatch(/open/i);
  });
});
