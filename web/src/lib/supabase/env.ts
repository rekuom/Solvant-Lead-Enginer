/** Supabase public configuration. Prefer the modern publishable key (sb_publishable_…); the legacy anon JWT is accepted
 *  as a fallback. Never configure a secret / service-role key here: the app does not need one. */
export const DB_SCHEMA = "solvant";

export function supabaseEnv(): { url: string; key: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (or legacy NEXT_PUBLIC_SUPABASE_ANON_KEY) must be set");
  }
  if (key.startsWith("sb_secret_")) {
    throw new Error("A Supabase SECRET key was configured as the public key. Use the publishable key.");
  }
  return { url, key };
}
