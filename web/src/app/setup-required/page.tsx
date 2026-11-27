export const metadata = { title: "Setup required" };
export const dynamic = "force-static";

/** Served only before the one-time server setup is complete. Contains no data and no login. */
export default function SetupRequired() {
  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center p-4">
      <div className="panel space-y-3 p-6 text-sm">
        <h1 className="text-lg font-semibold">Solvant Lead Engine: one-time setup</h1>
        <p>This private site opens only on your own devices. One server setting is needed (Vercel → Project → Settings → Environment Variables → Production):</p>
        <p><code>SUPABASE_SECRET_KEY</code>: from Supabase → Project Settings → API Keys → Secret key. Server-only.</p>
        <p>Redeploy. Then open the one-time device link you were given (it works once and expires after 15 minutes). After that, the site opens straight into the dashboard.</p>
      </div>
    </main>
  );
}
