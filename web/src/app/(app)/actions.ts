"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { STAGES } from "@/lib/labels";

type State = { error: string; ok?: string };
const STAGE_KEYS = new Set<string>(STAGES.map((s) => s.key));
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const str = (f: FormData, k: string, max = 2000) => String(f.get(k) ?? "").trim().slice(0, max);
const id = (f: FormData, k = "id") => {
  const v = str(f, k, 40);
  if (!UUID.test(v)) throw new Error("invalid id");
  return v;
};
const msg = (e: { message?: string } | null) => (e ? e.message ?? "Something went wrong" : "");

export async function claimAdmin(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const { error } = await supabase.rpc("claim_admin", { p_code: str(form, "code", 80) });
  if (error) return { error: "That code is invalid, expired or already used." };
  revalidatePath("/", "layout");
  redirect("/");
}

export async function setStage(form: FormData) {
  const supabase = await createClient();
  const stage = str(form, "stage", 40);
  if (!STAGE_KEYS.has(stage)) throw new Error("invalid stage");
  const patch: Record<string, unknown> = { stage };
  if (stage === "lost") patch.lost_reason = str(form, "reason", 300) || null;
  if (stage === "won") {
    patch.win_reason = str(form, "reason", 300) || null;
    const v = Number(str(form, "value", 20));
    if (Number.isFinite(v) && v > 0) patch.deal_value = v;
  }
  const { error } = await supabase.from("opportunities").update(patch).eq("id", id(form));
  if (error) throw new Error(error.message);
  revalidatePath("/", "layout");
}

export async function bulkUpdate(form: FormData) {
  const supabase = await createClient();
  const ids = form.getAll("ids").map(String).filter((v) => UUID.test(v)).slice(0, 200);
  if (!ids.length) return;
  const action = str(form, "bulk", 40);
  if (action === "assign_me") {
    const { data } = await supabase.auth.getUser();
    await supabase.from("opportunities").update({ owner_id: data.user?.id }).in("id", ids);
  } else if (STAGE_KEYS.has(action)) {
    await supabase.from("opportunities").update({ stage: action }).in("id", ids);
  }
  revalidatePath("/opportunities");
}

export async function updateDetails(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const followUp = str(form, "follow_up_at", 30);
  const value = str(form, "deal_value", 20);
  const owner = str(form, "owner_id", 40);
  const patch = {
    organisation: str(form, "organisation", 200) || null,
    country: str(form, "country", 80) || null,
    org_type: str(form, "org_type", 80) || null,
    budget_text: str(form, "budget_text", 120) || null,
    contact_route: str(form, "contact_route", 200) || null,
    technologies: str(form, "technologies", 400).split(",").map((t) => t.trim()).filter(Boolean).slice(0, 15),
    follow_up_at: followUp ? new Date(followUp).toISOString() : null,
    deal_value: value && Number.isFinite(Number(value)) ? Number(value) : null,
    deal_currency: (str(form, "deal_currency", 3) || "GBP").toUpperCase(),
    owner_id: UUID.test(owner) ? owner : null,
  };
  const { error } = await supabase.from("opportunities").update(patch).eq("id", id(form));
  revalidatePath(`/opportunities/${id(form)}`);
  return error ? { error: msg(error) } : { error: "", ok: "Saved" };
}

export async function addNote(form: FormData) {
  const supabase = await createClient();
  const body = str(form, "body", 5000);
  if (!body) return;
  const { error } = await supabase.from("notes").insert({ opportunity_id: id(form), body });
  if (error) throw new Error(error.message);
  revalidatePath(`/opportunities/${id(form)}`);
}

export async function logActivity(form: FormData) {
  const supabase = await createClient();
  const kind = str(form, "kind", 20);
  if (!["contact", "reply", "meeting", "proposal", "other"].includes(kind)) throw new Error("invalid kind");
  const { error } = await supabase.from("activities").insert({ opportunity_id: id(form), kind, summary: str(form, "summary", 500) || kind });
  if (error) throw new Error(error.message);
  revalidatePath(`/opportunities/${id(form)}`);
}

export async function addFollowUp(form: FormData) {
  const supabase = await createClient();
  const due = str(form, "due_at", 30);
  if (!due) return;
  const { data } = await supabase.auth.getUser();
  const { error } = await supabase.from("follow_ups").insert({
    opportunity_id: id(form), title: str(form, "title", 200) || "Follow up", due_at: new Date(due).toISOString(), assignee_id: data.user?.id,
  });
  if (error) throw new Error(error.message);
  revalidatePath(`/opportunities/${id(form)}`);
  revalidatePath("/follow-ups");
}

export async function completeFollowUp(form: FormData) {
  const supabase = await createClient();
  await supabase.from("follow_ups").update({ done_at: new Date().toISOString() }).eq("id", id(form));
  revalidatePath("/follow-ups");
  revalidatePath("/", "layout");
}

export async function addProposal(form: FormData) {
  const supabase = await createClient();
  const amount = Number(str(form, "amount", 20));
  const { error } = await supabase.from("proposals").insert({
    opportunity_id: id(form), title: str(form, "title", 200) || "Proposal", amount: Number.isFinite(amount) && amount > 0 ? amount : null,
    currency: (str(form, "currency", 3) || "GBP").toUpperCase(), status: str(form, "status", 20) || "sent",
    sent_at: new Date().toISOString(),
  });
  if (error) throw new Error(error.message);
  await supabase.from("activities").insert({ opportunity_id: id(form), kind: "proposal", summary: `Proposal: ${str(form, "title", 200)}` });
  revalidatePath(`/opportunities/${id(form)}`);
}

export async function addContactChannel(form: FormData) {
  const supabase = await createClient();
  const { error } = await supabase.from("contact_channels").insert({
    opportunity_id: id(form), kind: str(form, "kind", 40), value: str(form, "value", 300) || null,
    permission: str(form, "permission", 40) || "unknown", note: str(form, "note", 300) || null,
  });
  if (error) throw new Error(error.message);
  revalidatePath(`/opportunities/${id(form)}`);
}

export async function overrideClassification(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const dims: Record<string, string> = {};
  for (const k of ["buying_intent", "technical_relevance", "engagement_type", "business_type", "contact_permission"]) {
    const v = str(form, k, 60);
    if (v) dims[k] = v;
  }
  const { error } = await supabase.rpc("override_classification", {
    p_opp: id(form), p_pipeline: str(form, "pipeline", 40), p_priority: str(form, "priority", 1) || null, p_dims: dims,
    p_reason: str(form, "reason", 500),
  });
  revalidatePath(`/opportunities/${id(form)}`);
  return error ? { error: msg(error) } : { error: "", ok: "Classification corrected (history kept)" };
}

export async function verifyOpportunity(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const { error } = await supabase.rpc("verify_opportunity", { p_opp: id(form), p_note: str(form, "note", 2000) });
  revalidatePath(`/opportunities/${id(form)}`);
  return error ? { error: msg(error) } : { error: "", ok: "Marked as verified" };
}

export async function markDuplicate(form: FormData) {
  const supabase = await createClient();
  const { error } = await supabase.rpc("mark_duplicate", { p_opp: id(form), p_of: id(form, "of") });
  if (error) throw new Error(error.message);
  revalidatePath(`/opportunities/${id(form)}`);
}

export async function saveSearch(form: FormData) {
  const supabase = await createClient();
  const filters = JSON.parse(str(form, "filters", 2000) || "{}");
  const allowed = ["q", "pipeline", "source", "country", "tech", "verification", "stage", "priority"];
  const clean = Object.fromEntries(Object.entries(filters).filter(([k, v]) => allowed.includes(k) && typeof v === "string" && v));
  const { data: u } = await supabase.auth.getUser();
  const { error } = await supabase.from("saved_searches").insert({ user_id: u.user?.id, name: str(form, "name", 80) || "Saved search", filters: clean });
  if (error) throw new Error(error.message);
  revalidatePath("/searches");
  redirect("/searches");
}

export async function deleteSearch(form: FormData) {
  const supabase = await createClient();
  await supabase.from("saved_searches").delete().eq("id", id(form));
  revalidatePath("/searches");
}

export async function markNotificationsRead() {
  const supabase = await createClient();
  await supabase.from("notifications").update({ read_at: new Date().toISOString() }).is("read_at", null);
  revalidatePath("/", "layout");
}
