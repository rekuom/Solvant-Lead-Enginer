"use client";
import { createBrowserClient } from "@supabase/ssr";

// Inlined at build time (NEXT_PUBLIC_*). Browser code only ever uses the user's own session for data access.
const URL = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const KEY = (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY)!;

export function createClient() {
  return createBrowserClient(URL, KEY, { db: { schema: "solvant" } });
}
