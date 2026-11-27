import Link from "next/link";
import { requireMember } from "@/lib/session";
import { Badge, PageHeader, Section, fmtDate } from "@/components/ui";
import { microsoftConfigured } from "@/lib/server/microsoft";
import { checkRepliesAndBounces, disconnectMailbox } from "./actions";

export const metadata = { title: "Outreach" };

const ERRORS: Record<string, string> = {
  not_configured: "Microsoft sign-in is not configured yet (MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET in Vercel).",
  consent_declined: "Microsoft consent was cancelled.", invalid_state: "The connection attempt expired. Try again.",
  no_refresh_token: "Microsoft did not grant offline access. Try again and accept all requested permissions.",
  no_mailbox: "That Microsoft account has no mailbox.", store_failed: "Could not save the connection.", exchange_failed: "Microsoft sign-in failed. Try again.",
};

export default async function Outreach({ searchParams }: { searchParams: Promise<{ connected?: string; error?: string }> }) {
  const sp = await searchParams;
  const { supabase, role } = await requireMember();
  const [{ data: acct }, { data: emails }] = await Promise.all([
    supabase.from("mail_accounts").select("email,display_name,connected_at,last_used_at,last_error,active").eq("active", true).maybeSingle(),
    supabase.from("outreach_emails").select("id,opportunity_id,to_address,subject,status,error,sent_at,created_at,reply_detected_at,bounce_detected_at,bounce_detail")
      .order("created_at", { ascending: false }).limit(100),
  ]);
  const ids = [...new Set((emails ?? []).map((e) => e.opportunity_id).filter(Boolean))] as string[];
  const { data: opps } = ids.length ? await supabase.from("opportunities").select("id,title").in("id", ids) : { data: [] as { id: string; title: string }[] };
  const titles = new Map((opps ?? []).map((o) => [o.id, o.title]));
  const sent = (emails ?? []).filter((e) => e.status === "sent");
  return (
    <div className="space-y-5">
      <PageHeader title="Outreach" subtitle="E-mail sent from your own mailbox, with replies and delivery errors." />
      {sp.connected ? <div className="panel border-emerald-300 p-3 text-sm text-emerald-700">Mailbox connected.</div> : null}
      {sp.error ? <div className="panel border-amber-300 p-3 text-sm text-amber-800">{ERRORS[sp.error] ?? "Something went wrong."}</div> : null}

      <Section title="Mailbox">
        {acct ? (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Badge tone="green">Connected</Badge><b>{acct.email}</b>
            <span className="muted text-xs">since {fmtDate(acct.connected_at)}{acct.last_used_at ? ` · last used ${fmtDate(acct.last_used_at, true)}` : ""}</span>
            {acct.last_error ? <Badge tone="red" title={acct.last_error}>Needs reconnecting</Badge> : null}
            <a href="/api/email/connect" className="btn">Reconnect</a>
            {role === "admin" ? <form action={disconnectMailbox}><button className="btn btn-danger">Disconnect</button></form> : null}
          </div>
        ) : (
          <div className="space-y-2 text-sm">
            <p>Connect your Outlook / Live / Hotmail (or Microsoft 365) mailbox. Microsoft asks you to approve sending and reading mail; Solvant stores only an encrypted token on the server and never your password.</p>
            {microsoftConfigured() ? <a href="/api/email/connect" className="btn btn-primary">Connect Outlook</a>
              : <p className="text-amber-700">Microsoft sign-in is not configured yet: see the setup note in the handover (MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET).</p>}
          </div>
        )}
      </Section>

      <Section title={`Sent e-mails (${sent.length})`} actions={acct && sent.length ? <form action={checkRepliesAndBounces}><button className="btn">Check replies &amp; bounces</button></form> : null}>
        {(emails ?? []).length ? (
          <ul className="divide-y line text-sm">
            {(emails ?? []).map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-2 py-2">
                {e.status === "failed" ? <Badge tone="red" title={e.error ?? ""}>Failed</Badge>
                  : e.bounce_detected_at ? <Badge tone="red" title={e.bounce_detail ?? ""}>Bounced</Badge>
                  : e.reply_detected_at ? <Badge tone="green">Replied</Badge> : <Badge tone="blue">Sent</Badge>}
                <span className="min-w-0 flex-1 truncate"><b>{e.subject}</b> → {e.to_address}</span>
                {e.opportunity_id ? <Link className="text-xs text-brand-600 hover:underline" href={`/opportunities/${e.opportunity_id}`}>{titles.get(e.opportunity_id) ?? "lead"}</Link> : null}
                <span className="muted text-xs">{fmtDate(e.sent_at ?? e.created_at, true)}</span>
                {e.status === "failed" && e.error ? <span className="w-full text-xs text-red-600">{e.error}</span> : null}
              </li>
            ))}
          </ul>
        ) : <p className="muted text-sm">Nothing sent yet. Open a lead and use Compose e-mail.</p>}
      </Section>
    </div>
  );
}
