import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { DeviceForm } from "./device-form";

export const metadata = { title: "Authorise this device" };
export const dynamic = "force-dynamic";

/** Shown only to a device that has never been authorised (or was forgotten). Once authorised, the device opens the
 *  dashboard directly for ~400 days, renewed on every visit. */
export default async function DevicePage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (data.user) redirect("/");
  const sp = await searchParams;
  const owner = process.env.SOLVANT_OWNER_EMAIL || "";
  const hint = owner ? owner.replace(/^(.).*(@.*)$/, "$1•••$2") : "";
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 font-bold text-white">S</div>
          <h1 className="text-xl font-semibold">Authorise this device</h1>
          <p className="muted text-sm">One time only. After this, the Solvant Lead Engine opens straight into your dashboard on this device.</p>
        </div>
        <DeviceForm ownerEmail={owner} ownerHint={hint} linkError={Boolean(sp.error)} />
      </div>
    </main>
  );
}
