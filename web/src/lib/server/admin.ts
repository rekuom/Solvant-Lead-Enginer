import "server-only";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import { DB_SCHEMA, supabaseEnv } from "@/lib/supabase/env";

/** Server-only privileged client (SUPABASE_SECRET_KEY never leaves the server). Used for exactly two things:
 *  minting the owner's session for an authorised device, and reading/writing encrypted mailbox tokens.
 *  Everything else still runs as the owner under RLS. */
export function adminClient() {
  const { url } = supabaseEnv();
  const key = process.env.SUPABASE_SECRET_KEY;
  if (!key) throw new Error("SUPABASE_SECRET_KEY is not configured");
  return createSupabaseClient(url, key, { auth: { persistSession: false, autoRefreshToken: false }, db: { schema: DB_SCHEMA } });
}
