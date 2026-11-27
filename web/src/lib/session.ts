import "server-only";
import { cache } from "react";
import { notFound, redirect } from "next/navigation";
import { createClient } from "./supabase/server";

export type Role = "admin" | "editor" | "viewer";

/** Current user + membership role. Authorisation is still enforced by RLS on every query. */
export const getContext = cache(async () => {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) notFound();   // the proxy always provides the owner session to an authorised device
  const { data: role } = await supabase.rpc("my_role");
  return { supabase, user: data.user, role: (role as Role | null) ?? null };
});

export async function requireMember() {
  const ctx = await getContext();
  if (!ctx.role) redirect("/");
  return ctx;
}

export const canEdit = (role: Role | null) => role === "admin" || role === "editor";
