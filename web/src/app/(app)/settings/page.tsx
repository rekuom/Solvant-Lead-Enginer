import { requireMember } from "@/lib/session";
import { Badge, PageHeader, Section, fmtDate } from "@/components/ui";
import { revokeDevice, revokeIngestToken } from "../admin-actions";
import { AddDeviceForm, LlmForm, PurgeForm, TokenForm } from "./forms";

export const metadata = { title: "Settings" };

export default async function Settings() {
  const { supabase, role, user } = await requireMember();
  const admin = role === "admin";
  const [{ data: tokens }, { data: settings }, { data: devices }] = await Promise.all([
    admin ? supabase.from("ingest_tokens").select("id,name,scopes,created_at,last_used_at,revoked_at").order("created_at", { ascending: false }) : Promise.resolve({ data: [] }),
    supabase.from("app_settings").select("key,value"),
    admin ? supabase.from("devices").select("id,label,created_at,last_seen_at,revoked_at").order("created_at", { ascending: false }) : Promise.resolve({ data: [] }),
  ]);
  const setting = (k: string) => (settings ?? []).find((s) => s.key === k)?.value ?? {};
  return (
    <div className="space-y-5">
      <PageHeader title="Settings" subtitle="Private workspace · this device is trusted" />
      <Section title="Devices with access">
        <ul className="mb-3 divide-y line text-sm">
          {((devices ?? []) as { id: string; label: string | null; created_at: string; last_seen_at: string | null; revoked_at: string | null }[]).map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="min-w-0 flex-1 truncate">{d.label || "Device"}</span>
              <span className="muted text-xs">added {fmtDate(d.created_at)}{d.last_seen_at ? ` · last used ${fmtDate(d.last_seen_at)}` : ""}</span>
              {d.revoked_at ? <Badge tone="gray">Revoked</Badge> : admin ? <form action={revokeDevice}><input type="hidden" name="id" value={d.id} /><button className="btn btn-danger">Revoke</button></form> : null}
            </li>
          ))}
        </ul>
        {admin ? <AddDeviceForm /> : null}
        <form action="/api/device/forget" method="post" className="mt-3"><button className="btn">Remove access from this device</button></form>
      </Section>

      {admin ? (
        <Section title="Discovery connection (GitHub Actions → private database)">
          <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm">
            <li>Create a <b>Discovery</b> token below and copy it.</li>
            <li>In GitHub: <b>rekuom/Solvant-Lead-Enginer → Settings → Secrets and variables → Actions</b>: add secret <code>SIGNAL_INGEST_TOKEN</code>.</li>
            <li>Add repository variables <code>SUPABASE_URL</code> and <code>SUPABASE_PUBLISHABLE_KEY</code> (public values; the <code>sb_publishable_…</code> key).</li>
            <li>Set variable <code>DISCOVERY_SCHEDULE_ENABLED</code> = <code>true</code> to let the Sources page settings drive hourly-evaluated automatic collection.</li>
          </ol>
          <TokenForm />
          <ul className="mt-3 divide-y line text-sm">
            {((tokens ?? []) as any[]).map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-2 py-2">
                <span className="flex-1">{t.name} <span className="muted text-xs">({t.scopes.join(", ")}) · created {fmtDate(t.created_at)} · last used {fmtDate(t.last_used_at, true)}</span></span>
                {t.revoked_at ? <Badge tone="red">revoked</Badge> : <form action={revokeIngestToken}><input type="hidden" name="id" value={t.id} /><button className="btn btn-danger">Revoke</button></form>}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section title="Inbound e-mail (forward marketplace alerts automatically)">
        <p className="text-sm">Status: <Badge tone="amber">Awaiting an inbound-email provider</Badge></p>
        <p className="muted mt-1 text-sm">The receiving endpoint is built (<code>/api/engine/inbound-email</code>). It needs an inbound-email service (for example Postmark, Mailgun or Cloudflare Email Workers) that posts the raw message with an <b>Inbound e-mail</b> token. Choosing and paying for a provider is your decision; until then, upload alert files on Add leads.</p>
      </Section>

      {admin ? (
        <Section title="Optional LLM assessment (budget-capped)">
          <p className="muted mb-2 text-sm">Deterministic rules classify every record. An LLM second opinion can be enabled only with a monthly budget above zero; it is off by default and nothing is called today.</p>
          <LlmForm value={setting("llm") as Record<string, any>} />
        </Section>
      ) : null}

      {admin ? (
        <Section title="Data retention">
          <p className="text-sm">Excerpts are kept for <b>{String(setting("retention_days")) || "365"}</b> days, then removed from records that never progressed beyond review
            (including linked evidence copies and derived evidence snippets). Records, classification history and activity entries remain; audit rows are kept for{" "}
            <b>{String((setting("retention_policy") as Record<string, unknown>).audit_days ?? 730)}</b> days.</p>
          <p className="mt-1 text-sm">Automatic daily enforcement:{" "}
            {(setting("retention_policy") as Record<string, unknown>).enabled
              ? <Badge tone="green">enabled</Badge>
              : <Badge tone="amber">disabled — awaiting approval of the retention rules</Badge>}</p>
          <div className="mt-2"><PurgeForm /></div>
        </Section>
      ) : null}
    </div>
  );
}
