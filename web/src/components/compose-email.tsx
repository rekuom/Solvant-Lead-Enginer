"use client";
import { useActionState, useState } from "react";
import { sendOutreachEmail } from "@/app/(app)/outreach/actions";

type Props = { opportunityId: string; to: string; toPermitted: boolean; subject: string; body: string; proposalId: string | null; mailbox: string | null };

/** Compose and send one e-mail from the connected mailbox. Nothing is sent until you click Send. */
export function ComposeEmail(p: Props) {
  const [state, action, pending] = useActionState(sendOutreachEmail, { error: "" });
  const [to, setTo] = useState(p.to);
  const permittedAddress = p.toPermitted && to.toLowerCase() === p.to.toLowerCase();
  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="opportunity_id" value={p.opportunityId} />
      {p.proposalId ? <input type="hidden" name="proposal_id" value={p.proposalId} /> : null}
      <p className="muted text-xs">From: <b>{p.mailbox}</b>{p.proposalId ? " · the proposal draft is inserted below. Edit freely before sending." : ""}</p>
      <input name="to" type="email" className="input" placeholder="Recipient e-mail" value={to} onChange={(e) => setTo(e.target.value)} required maxLength={320} />
      <input name="subject" className="input" defaultValue={p.subject} required maxLength={300} />
      <textarea name="body" className="input min-h-64 font-sans" defaultValue={p.body} required maxLength={20000} />
      {!permittedAddress ? (
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" name="confirm_permitted" className="mt-0.5" />
          <span>I confirm this is a business address the buyer published or invited me to use.</span>
        </label>
      ) : <p className="text-xs text-emerald-700">Recipient taken from the lead&apos;s permitted business contact.</p>}
      <button className="btn btn-primary" disabled={pending}>{pending ? "Sending…" : "Send e-mail"}</button>
      {state.error ? <p className="text-sm text-red-600" role="alert">{state.error}</p> : null}
      {state.ok ? <p className="text-sm text-emerald-700" role="status">{state.ok}</p> : null}
    </form>
  );
}
