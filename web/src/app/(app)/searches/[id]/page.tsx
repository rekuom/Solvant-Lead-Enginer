import { notFound, redirect } from "next/navigation";
import { requireMember } from "@/lib/session";
import { toQuery } from "@/lib/filters";

export default async function OpenSearch({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const { supabase } = await requireMember();
  const { data } = await supabase.from("saved_searches").select("filters,last_seen_at").eq("id", id).maybeSingle();
  if (!data) notFound();
  await supabase.from("saved_searches").update({ last_seen_at: new Date().toISOString() }).eq("id", id);
  const since = new Date(data.last_seen_at).toISOString().slice(0, 10);
  redirect(`/opportunities${toQuery({ ...(data.filters as object), from: since })}`);
}
