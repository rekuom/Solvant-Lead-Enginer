"use server";
import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

type State = { error: string; ok?: string; token?: string };
const str = (f: FormData, k: string, max = 300) => String(f.get(k) ?? "").trim().slice(0, max);
const CRON = /^([0-9*,\/-]+\s){4}[0-9*,\/-]+$/;

export async function updateSource(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const key = str(form, "key", 80);
  const schedule = str(form, "schedule_cron", 60);
  if (schedule && !CRON.test(schedule)) return { error: "Schedule must be a 5-field cron expression (UTC)" };
  const budget = Number(str(form, "monthly_budget_usd", 12) || 0);
  if (!Number.isFinite(budget) || budget < 0) return { error: "Budget must be zero or more" };
  const { error } = await supabase.from("sources").update({
    enabled: form.get("enabled") === "on", schedule_cron: schedule || null, monthly_budget_usd: budget,
    notes: str(form, "notes", 2000) || null,
  }).eq("key", key);
  revalidatePath("/sources");
  if (error) {
    return { error: error.message.includes("sources_enable_guard")
      ? "Blocked: this source's permission status (unknown/prohibited) or a missing budget for a paid source prevents automated collection."
      : error.message };
  }
  return { error: "", ok: "Saved" };
}

export async function createIngestToken(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const scope = str(form, "scope", 20) === "inbound_email" ? "inbound_email" : "discovery";
  const { data, error } = await supabase.rpc("create_ingest_token", { p_name: str(form, "name", 60) || scope, p_scopes: [scope] });
  revalidatePath("/settings");
  return error ? { error: error.message } : { error: "", ok: "Token created — copy it now; it will not be shown again.", token: String(data) };
}

export async function revokeIngestToken(form: FormData) {
  const supabase = await createClient();
  await supabase.rpc("revoke_ingest_token", { p_id: str(form, "id", 40) });
  revalidatePath("/settings");
}

export async function addMember(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const role = str(form, "role", 10);
  if (!["admin", "editor", "viewer"].includes(role)) return { error: "Invalid role" };
  const { error } = await supabase.rpc("add_member", { p_email: str(form, "email", 200), p_role: role });
  revalidatePath("/settings");
  return error ? { error: error.message } : { error: "", ok: "Member saved" };
}

export async function removeMember(form: FormData) {
  const supabase = await createClient();
  await supabase.rpc("remove_member", { p_user: str(form, "user_id", 40) });
  revalidatePath("/settings");
}

export async function saveLlmSettings(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const budget = Number(str(form, "monthly_budget_usd", 12) || 0);
  const value = {
    enabled: form.get("enabled") === "on" && budget > 0, provider: str(form, "provider", 40) || null, model: str(form, "model", 80) || null,
    monthly_budget_usd: Number.isFinite(budget) ? Math.max(0, budget) : 0, per_record_max_usd: 0.01,
  };
  const { error } = await supabase.from("app_settings").upsert({ key: "llm", value });
  revalidatePath("/settings");
  return error ? { error: error.message } : { error: "", ok: value.enabled ? "Saved" : "Saved (LLM assessment stays off until a budget above zero is set)" };
}

export async function addCost(_: State, form: FormData): Promise<State> {
  const supabase = await createClient();
  const amount = Number(str(form, "amount", 12));
  if (!Number.isFinite(amount) || amount < 0) return { error: "Amount must be a number" };
  const { error } = await supabase.from("acquisition_costs").insert({
    source_key: str(form, "source_key", 80) || null, amount, currency: (str(form, "currency", 3) || "GBP").toUpperCase(),
    kind: str(form, "kind", 20) || "lead_purchase", description: str(form, "description", 300) || null,
    licence_terms: str(form, "licence_terms", 300) || null, incurred_on: str(form, "incurred_on", 10) || undefined,
  });
  revalidatePath("/analytics");
  return error ? { error: error.message } : { error: "", ok: "Cost recorded" };
}

export async function purgeExpired(_: State): Promise<State> {
  const supabase = await createClient();
  const { data, error } = await supabase.rpc("purge_expired_excerpts");
  return error ? { error: error.message } : { error: "", ok: `${data ?? 0} expired excerpt(s) removed` };
}
