export const metadata = { title: "Setup required" };
export const dynamic = "force-static";

/** Served only before the one-time server setup is complete. Contains no data and no login. */
export default function SetupRequired() {
  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center p-4">
      <div className="panel space-y-3 p-6 text-sm">
        <h1 className="text-lg font-semibold">Solvant Lead Engine: one-time setup</h1>
        <p>This private site opens only on your own devices. Two server settings are needed once (Vercel → Project → Settings → Environment Variables):</p>
        <ol className="list-decimal space-y-1 pl-5">
          <li><code>SOLVANT_ACCESS_KEY</code>: a long random phrase you choose (at least 24 characters). Keep it private.</li>
          <li><code>SUPABASE_SECRET_KEY</code>: from Supabase → Project Settings → API Keys → Secret key. Server-only.</li>
        </ol>
        <p>Redeploy, then open <code>/setup?key=YOUR_ACCESS_KEY</code> once on each of your devices. After that the site opens straight into the dashboard.</p>
      </div>
    </main>
  );
}
