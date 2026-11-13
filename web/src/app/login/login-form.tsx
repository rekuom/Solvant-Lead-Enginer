"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export function LoginForm({ next, initialError }: { next: string; initialError?: string }) {
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(initialError ? "Sign-in link was invalid or expired." : null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const supabase = createClient();
    if (mode === "signin") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      setBusy(false);
      if (error) return setMsg(error.message);
      router.replace(next);
      router.refresh();
    } else {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}` },
      });
      setBusy(false);
      setMsg(error ? error.message : "Check your inbox to confirm your e-mail, then sign in. An admin must grant you access.");
    }
  }

  return (
    <form onSubmit={submit} className="panel space-y-3 p-5">
      <div>
        <label className="label" htmlFor="email">E-mail</label>
        <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div>
        <label className="label" htmlFor="password">Password</label>
        <input id="password" className="input" type="password" minLength={10} required value={password}
          autoComplete={mode === "signin" ? "current-password" : "new-password"} onChange={(e) => setPassword(e.target.value)} />
      </div>
      {msg ? <p className="text-sm text-amber-700 dark:text-amber-300" role="status">{msg}</p> : null}
      <button className="btn btn-primary w-full justify-center" disabled={busy}>{busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}</button>
      <button type="button" className="muted w-full text-center text-xs underline" onClick={() => setMode(mode === "signin" ? "signup" : "signin")}>
        {mode === "signin" ? "First time here? Create an account" : "Already have an account? Sign in"}
      </button>
    </form>
  );
}
