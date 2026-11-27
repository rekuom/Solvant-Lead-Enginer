"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

/** One-time device authorisation: a sign-in link e-mailed to the owner (no new accounts can be created here).
 *  The owner's password works as a fallback. The session then persists on this device. */
export function DeviceForm({ ownerEmail, ownerHint, linkError }: { ownerEmail: string; ownerHint: string; linkError: boolean }) {
  const router = useRouter();
  const [email, setEmail] = useState(ownerEmail);
  const [password, setPassword] = useState("");
  const [usePassword, setUsePassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(linkError ? "That link was invalid or expired. Send a new one." : null);

  async function sendLink() {
    setBusy(true);
    setMsg(null);
    const { error } = await createClient().auth.signInWithOtp({
      email,
      options: { shouldCreateUser: false, emailRedirectTo: `${window.location.origin}/auth/callback?next=/` },
    });
    setBusy(false);
    setMsg(error ? "Could not send the link. Try the password option below." : "Check your inbox and open the link on this device. That's it.");
  }

  async function withPassword(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const { error } = await createClient().auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) return setMsg("Those details didn't work.");
    router.replace("/");
    router.refresh();
  }

  return (
    <div className="panel space-y-3 p-5">
      {ownerEmail ? (
        <p className="text-sm">Send a one-time link to <b>{ownerHint}</b>.</p>
      ) : (
        <div>
          <label className="label" htmlFor="email">Your e-mail</label>
          <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
      )}
      {!usePassword ? (
        <button className="btn btn-primary w-full justify-center" disabled={busy || !email} onClick={sendLink}>
          {busy ? "Sending…" : "Authorise this device"}
        </button>
      ) : (
        <form onSubmit={withPassword} className="space-y-2">
          <input className="input" type="password" autoComplete="current-password" placeholder="Password" required value={password}
            onChange={(e) => setPassword(e.target.value)} />
          <button className="btn btn-primary w-full justify-center" disabled={busy || !email}>{busy ? "Checking…" : "Authorise with password"}</button>
        </form>
      )}
      {msg ? <p className="text-sm text-amber-700 dark:text-amber-300" role="status">{msg}</p> : null}
      <button type="button" className="muted w-full text-center text-xs underline" onClick={() => setUsePassword(!usePassword)}>
        {usePassword ? "Use an e-mailed link instead" : "Use my password instead"}
      </button>
    </div>
  );
}
