import { requireMember, canEdit } from "@/lib/session";
import { PageHeader, Empty } from "@/components/ui";
import { IntakeForms } from "./intake-forms";

export const metadata = { title: "Add leads" };

export default async function Intake() {
  const { supabase, role } = await requireMember();
  if (!canEdit(role)) return <Empty title="Read-only access">Ask an admin for editor access to add leads.</Empty>;
  const { data: sources } = await supabase.from("sources").select("key,name,permission_status,family").order("name");
  return (
    <div>
      <PageHeader title="Add leads" subtitle="Paste a post, upload a marketplace alert or a CSV — from desktop or phone." />
      <IntakeForms sources={(sources ?? []) as never} />
    </div>
  );
}
