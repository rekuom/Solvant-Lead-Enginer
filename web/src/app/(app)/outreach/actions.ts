"use server";
import { revalidatePath } from "next/cache";
import { requireMember, canEdit } from "@/lib/session";
import { adminClient } from "@/lib/server/admin";
import { bounceNotices, refreshAccess, repliesFrom, sendMail } from "@/lib/server/microsoft";
import { decryptToken, encryptToken } from "@/lib/server/token-crypto";

type State = { error: string; ok?: string };
const EMAIL = /^[^\s@<>"']{1,64}@[a-z0-9.-]{1,253}\.[a-z]{2,24}$/i;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const str = (f: FormData, k: string, max: number) => String(f.get(k) ?? "").trim().slice(0, max);
const ADVANCE_TO_CONTACTED = ["discovered", "needs_review", "verified", "qualified", "contact_planned"];

/** Active mailbox + a fresh access token (Microsoft rotates refresh tokens: the new one is stored encrypted). */
async function mailbox() {
  const admin = adminClient();
  const { data: acct } = await admin.from("mail_accounts").select("id,email,refresh_token_enc").eq("active", true).limit(1).maybeSingle();
  if (!acct) throw new Error("Connect your Outlook mailbox first (Outreach page).");
  try {
    const t = await refreshAccess(decryptToken(acct.refresh_token_enc));
    await admin.from("mail_accounts").update({
      last_used_at: new Date().toISOString(), last_error: null,
      ...(t.refresh_token ? { refresh_token_enc: encryptToken(t.refresh_token) } : {}),
    }).eq("id", acct.id);
    return { admin, acct, token: t.access_token };
  } catch (e) {
    await admin.from("mail_accounts").update({ last_error: (e instanceof Error ? e.message : "token refresh failed").slice(0, 500) }).eq("id", acct.id);
    throw new Error("Your Outlook connection has expired. Reconnect it on the Outreach page.");
  }
}

/** Sends ONE real e-mail from the connected mailbox, only when the owner clicks Send. Marketplace projects (in-platform
 *  contact only) and do-not-contact leads are refused; a manually typed address needs explicit confirmation. */
export async function sendOutreachEmail(_: State, form: FormData): Promise<State> {
  const { supabase, role } = await requireMember();
  if (!canEdit(role)) return { error: "Not allowed." };
  const oppId = str(form, "opportunity_id", 40);
  if (!UUID.test(oppId)) return { error: "Invalid lead." };
  const to = str(form, "to", 320).toLowerCase();
  const subject = str(form, "subject", 300);
  const body = str(form, "body", 20000);
  const proposalId = str(form, "proposal_id", 40);
  if (!EMAIL.test(to)) return { error: "Enter a valid recipient e-mail address." };
  if (!subject || !body) return { error: "Subject and message are required." };

  const { data: o } = await supabase.from("opportunities").select("id,title,stage,meta").eq("id", oppId).maybeSingle();
  if (!o) return { error: "Lead not found." };
  if (o.meta?.action?.type === "submit_proposal") return { error: "This is a marketplace project: contact must stay on the platform. Submit the proposal there instead." };
  const { data: chans } = await supabase.from("contact_channels").select("value,permission,kind").eq("opportunity_id", oppId);
  const match = (chans ?? []).find((c) => (c.value ?? "").toLowerCase() === to);
  if (match?.permission === "do_not_contact") return { error: "This contact is marked do-not-contact." };
  const permitted = match && ["invited", "published_for_business"].includes(match.permission);
  if (!permitted && form.get("confirm_permitted") !== "on")
    return { error: "Confirm that this is a business address the buyer published or invited you to use." };

  let m;
  try {
    m = await mailbox();
  } catch (e) {
    return { error: e instanceof Error ? e.message : "Mailbox unavailable." };
  }
  const base = { opportunity_id: oppId, mail_account_id: m.acct.id, from_address: m.acct.email, to_address: to, subject, body,
                 proposal_id: UUID.test(proposalId) ? proposalId : null };
  try {
    await sendMail(m.token, to, subject, body);
  } catch (e) {
    const msg = (e instanceof Error ? e.message : "Send failed").slice(0, 500);
    await m.admin.from("outreach_emails").insert({ ...base, status: "failed", error: msg });
    revalidatePath(`/opportunities/${oppId}`);
    return { error: `Not sent: ${msg}` };
  }
  await m.admin.from("outreach_emails").insert({ ...base, status: "sent", sent_at: new Date().toISOString() });
  await supabase.from("activities").insert({ opportunity_id: oppId, kind: "contact", summary: `E-mail sent to ${to}: ${subject}`.slice(0, 500) });
  if (ADVANCE_TO_CONTACTED.includes(o.stage)) await supabase.from("opportunities").update({ stage: "contacted" }).eq("id", oppId);
  if (base.proposal_id) {
    await supabase.from("proposals").update({ status: "sent", sent_at: new Date().toISOString() }).eq("id", base.proposal_id).eq("status", "draft");
  }
  revalidatePath(`/opportunities/${oppId}`);
  revalidatePath("/outreach");
  return { error: "", ok: `Sent to ${to} from ${m.acct.email}.` };
}

export async function disconnectMailbox(): Promise<void> {
  const { role } = await requireMember();
  if (role !== "admin") throw new Error("Not allowed");
  await adminClient().from("mail_accounts").delete().eq("provider", "microsoft");
  revalidatePath("/outreach");
}

/** Looks in the connected mailbox for replies from recipients and for non-delivery reports. Updates the log and funnel. */
export async function checkRepliesAndBounces(): Promise<void> {
  const { supabase, role } = await requireMember();
  if (!canEdit(role)) throw new Error("Not allowed");
  const m = await mailbox();
  const since = new Date(Date.now() - 45 * 864e5).toISOString();
  const { data: sent } = await m.admin.from("outreach_emails").select("id,opportunity_id,to_address,subject,sent_at")
    .eq("status", "sent").is("reply_detected_at", null).gte("sent_at", since).limit(50);
  if (!sent?.length) return;
  const bounces = await bounceNotices(m.token, sent.map((s) => s.sent_at!).sort()[0]);
  for (const s of sent) {
    const bounce = bounces.find((b) => b.preview.toLowerCase().includes(s.to_address) || b.subject.includes(s.subject));
    if (bounce) {
      await m.admin.from("outreach_emails").update({ bounce_detected_at: new Date().toISOString(), bounce_detail: bounce.subject.slice(0, 300) }).eq("id", s.id);
      continue;
    }
    if ((await repliesFrom(m.token, s.to_address, s.sent_at!)) > 0) {
      await m.admin.from("outreach_emails").update({ reply_detected_at: new Date().toISOString() }).eq("id", s.id);
      if (s.opportunity_id) {
        await supabase.from("activities").insert({ opportunity_id: s.opportunity_id, kind: "reply", summary: `Reply received from ${s.to_address}` });
        const { data: o } = await supabase.from("opportunities").select("stage").eq("id", s.opportunity_id).maybeSingle();
        if (o && [...ADVANCE_TO_CONTACTED, "contacted"].includes(o.stage)) await supabase.from("opportunities").update({ stage: "replied" }).eq("id", s.opportunity_id);
      }
    }
  }
  revalidatePath("/outreach");
}
