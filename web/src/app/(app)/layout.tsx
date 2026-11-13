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
          <h1 className="text-lg font-semibold">Access pending</h1>
          <p className="muted text-sm">
            You are signed in as <b>{user.email}</b>, but this workspace is private. An administrator must add you as a member.
            If you are the owner setting this up for the first time, enter the one-time setup code.
          </p>
          <ClaimAccess />
          <form action="/auth/signout" method="post"><button className="btn w-full justify-center">Sign out</button></form>
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
