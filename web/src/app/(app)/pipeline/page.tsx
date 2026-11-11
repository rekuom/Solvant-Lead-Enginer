import { requireMember, canEdit } from "@/lib/session";
import { PageHeader, Empty } from "@/components/ui";
import { PIPELINES } from "@/lib/labels";
import { Board } from "./board";
import Link from "next/link";

export const metadata = { title: "Pipeline" };

export default async function Pipeline({ searchParams }: { searchParams: Promise<{ pipeline?: string }> }) {
  const { supabase, role } = await requireMember();
  const sp = await searchParams;
  const pipe = PIPELINES.some((p) => p.key === sp.pipeline) ? sp.pipeline : undefined;
  let q = supabase.from("opportunities").select("id,title,stage,pipeline,source_key,deal_value,follow_up_at,organisation")
    .neq("pipeline", "EXCLUDED").neq("stage", "archived").order("rank_score", { ascending: false }).limit(500);
  if (pipe) q = q.eq("pipeline", pipe);
  const { data } = await q;
  return (
    <div>
      <PageHeader title="Sales pipeline" subtitle="Drag cards between stages (or use the menu on each card). Internal tracking only — nothing is sent to anyone."
        actions={<div className="flex flex-wrap gap-1 text-sm">
          <Link href="/pipeline" className={`btn ${!pipe ? "btn-primary" : ""}`}>All</Link>
          {PIPELINES.filter((p) => p.key !== "EXCLUDED").map((p) => (
            <Link key={p.key} href={`/pipeline?pipeline=${p.key}`} className={`btn ${pipe === p.key ? "btn-primary" : ""}`}>{p.letter}</Link>
          ))}
        </div>} />
      {data?.length ? <Board cards={data as never} editable={canEdit(role)} /> : <Empty title="The pipeline is empty">Add a lead or run discovery; new records appear under “Needs review”.</Empty>}
    </div>
  );
}
