import { LoginForm } from "./login-form";

export const metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string; error?: string }> }) {
  const sp = await searchParams;
  const next = sp.next && sp.next.startsWith("/") && !sp.next.startsWith("//") ? sp.next : "/";
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 font-bold text-white">S</div>
          <h1 className="text-xl font-semibold">Solvant Signal Engine</h1>
          <p className="muted text-sm">Private workspace — members only</p>
        </div>
        <LoginForm next={next} initialError={sp.error} />
      </div>
    </main>
  );
}
