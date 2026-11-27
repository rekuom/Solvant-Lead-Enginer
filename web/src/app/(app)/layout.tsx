import { getContext } from "@/lib/session";
import { Nav } from "@/components/nav";
import { ClaimAccess } from "./claim-access";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { supabase, user, role } = await getContext();
  if (!role) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center p-4">
        <div className="panel space-y-3 p-6">
          <h1 className="text-lg font-semibold">This device isn&apos;t authorised for the workspace</h1>
          <p className="muted text-sm">It is signed in as <b>{user.email}</b>, which is not the owner account. First-time setup only: enter the one-time setup code.</p>
          <ClaimAccess />
          <form action="/auth/signout" method="post"><button className="btn w-full justify-center">Use a different account</button></form>
        </div>
      </main>
    );
  }
  const { data: unread } = await supabase.rpc("refresh_my_notifications");
  return (
    <>
      <Nav unread={typeof unread === "number" ? unread : 0} email={user.email ?? ""} role={role} />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </>
  );
}
