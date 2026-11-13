import Link from "next/link";
import { requireMember } from "@/lib/session";
import { PageHeader, Empty, fmtDate } from "@/components/ui";
import { deleteSearch } from "../actions";

export const metadata = { title: "Saved searches" };

export default async function Searches() {
  const { supabase } = await requireMember();
  const { data } = await supabase.from("saved_searches").select("*").order("created_at", { ascending: false });
  return (
    <div>
      <PageHeader title="Saved searches" subtitle="You are notified in-app when new opportunities match. Save a search from the Opportunities page." />
      {!data?.length ? <Empty title="No saved searches yet">Filter the opportunity list, then choose “Save search”.</Empty> : (
        <div className="panel overflow-x-auto"><table className="data"><thead><tr><th>Name</th><th>Filters</th><th>Last viewed</th><th></th></tr></thead><tbody>
          {data.map((s) => (
            <tr key={s.id}>
              <td><Link className="font-medium hover:underline" href={`/searches/${s.id}`}>{s.name}</Link></td>
              <td className="muted text-xs">{Object.entries(s.filters ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || "all"}</td>
              <td>{fmtDate(s.last_seen_at, true)}</td>
              <td><form action={deleteSearch}><input type="hidden" name="id" value={s.id} /><button className="btn btn-danger">Delete</button></form></td>
            </tr>
          ))}
        </tbody></table></div>
      )}
    </div>
  );
}
