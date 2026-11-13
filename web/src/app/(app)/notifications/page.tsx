import Link from "next/link";
import { requireMember } from "@/lib/session";
import { PageHeader, Empty, fmtDate, Badge } from "@/components/ui";
import { markNotificationsRead } from "../actions";

export const metadata = { title: "Notifications" };

export default async function Notifications() {
  const { supabase } = await requireMember();
  const { data } = await supabase.from("notifications").select("*").order("created_at", { ascending: false }).limit(100);
  return (
    <div>
      <PageHeader title="Notifications" actions={<form action={markNotificationsRead}><button className="btn">Mark all read</button></form>} />
      {!data?.length ? <Empty title="No notifications">Follow-up reminders, saved-search matches and failing sources appear here.</Empty> : (
        <ul className="panel divide-y line">
          {data.map((n) => (
            <li key={n.id} className={`flex flex-wrap items-center gap-2 p-3 ${n.read_at ? "muted" : ""}`}>
              <Badge tone={n.kind === "source_failing" ? "red" : n.kind === "follow_up_due" ? "amber" : "blue"}>{n.kind.replace(/_/g, " ")}</Badge>
              {n.link ? <Link href={n.link} className="font-medium hover:underline">{n.title}</Link> : <span className="font-medium">{n.title}</span>}
              {n.body ? <span className="text-sm">— {n.body}</span> : null}
              <span className="ml-auto text-xs">{fmtDate(n.created_at, true)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
