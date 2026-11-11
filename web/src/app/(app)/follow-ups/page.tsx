import Link from "next/link";
import { requireMember, canEdit } from "@/lib/session";
import { PageHeader, Empty, fmtDate, Badge } from "@/components/ui";
import { completeFollowUp } from "../actions";
import { STAGE_LABEL } from "@/lib/labels";

export const metadata = { title: "Follow-ups" };

export default async function FollowUps() {
  const { supabase, role } = await requireMember();
  const [{ data: tasks }, { data: dated }] = await Promise.all([
    supabase.from("follow_ups").select("id,title,due_at,opportunity_id,opportunities(title)").is("done_at", null).order("due_at").limit(200),
    supabase.from("opportunities").select("id,title,follow_up_at,stage").not("follow_up_at", "is", null)
      .not("stage", "in", "(won,lost,archived)").order("follow_up_at").limit(200),
  ]);
  const now = Date.now();
  return (
    <div className="space-y-5">
      <PageHeader title="Follow-ups" subtitle="Reminders appear here and in your notifications. E-mail reminders are optional (not configured)." />
      {!tasks?.length && !dated?.length ? <Empty title="Nothing scheduled">Set a follow-up date on any opportunity.</Empty> : null}
      {tasks?.length ? (
        <div className="panel overflow-x-auto"><table className="data"><thead><tr><th>Due</th><th>Task</th><th>Opportunity</th><th></th></tr></thead><tbody>
          {tasks.map((t: any) => (
            <tr key={t.id}>
              <td className="whitespace-nowrap">{new Date(t.due_at).getTime() < now ? <Badge tone="red">Overdue</Badge> : null} {fmtDate(t.due_at, true)}</td>
              <td>{t.title}</td>
              <td><Link className="hover:underline" href={`/opportunities/${t.opportunity_id}`}>{t.opportunities?.title ?? "Open"}</Link></td>
              <td>{canEdit(role) ? <form action={completeFollowUp}><input type="hidden" name="id" value={t.id} /><button className="btn">Done</button></form> : null}</td>
            </tr>
          ))}
        </tbody></table></div>
      ) : null}
      {dated?.length ? (
        <div className="panel overflow-x-auto"><table className="data"><thead><tr><th>Follow-up date</th><th>Opportunity</th><th>Stage</th></tr></thead><tbody>
          {dated.map((o) => (
            <tr key={o.id}>
              <td className="whitespace-nowrap">{new Date(o.follow_up_at!).getTime() < now ? <Badge tone="red">Overdue</Badge> : null} {fmtDate(o.follow_up_at, true)}</td>
              <td><Link className="hover:underline" href={`/opportunities/${o.id}`}>{o.title}</Link></td>
              <td>{STAGE_LABEL[o.stage]}</td>
            </tr>
          ))}
        </tbody></table></div>
      ) : null}
    </div>
  );
}
