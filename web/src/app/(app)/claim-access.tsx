"use client";
import { useActionState } from "react";
import { claimAdmin } from "./actions";

export function ClaimAccess() {
  const [state, action, pending] = useActionState(claimAdmin, { error: "" });
  return (
    <form action={action} className="space-y-2">
      <label className="label" htmlFor="code">One-time setup code</label>
      <input id="code" name="code" className="input font-mono" autoComplete="off" required minLength={32} maxLength={80} />
      {state.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
      <button className="btn btn-primary w-full justify-center" disabled={pending}>{pending ? "Checking…" : "Claim admin access"}</button>
    </form>
  );
}
