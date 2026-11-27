import { createServerClient } from "@supabase/ssr";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { DEVICE_COOKIE } from "@/lib/supabase/cookies";
import { DEVICE_COOKIE_NAME, DEVICE_MAX_AGE, accessKey, configured, deviceAllowed, deviceToken, hostAllowed, safeEqual } from "@/lib/server/device";

/** Private-tool gate. No login screen anywhere:
 *  1. any host other than the production domain → 404 (alternative/preview Vercel URLs are unusable);
 *  2. /setup?key=<SOLVANT_ACCESS_KEY> once per device → sets the httpOnly device cookie and opens the dashboard;
 *  3. every other request without a valid device cookie → plain 404;
 *  4. an authorised device gets the owner's Supabase session automatically (minted server-side with the secret key when
 *     missing or expired), so every page and query keeps running as the owner under RLS. */
const notFound = () => new NextResponse("Not found", { status: 404, headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex" } });

export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (!hostAllowed(request.headers.get("host"))) return notFound();

  if (!configured()) {
    // before the one-time setup: only the static setup instructions are served, never data
    if (path === "/setup-required") return NextResponse.next();
    const r = request.nextUrl.clone();
    r.pathname = "/setup-required";
    r.search = "";
    return NextResponse.redirect(r);
  }

  if (path === "/setup") {
    const given = request.nextUrl.searchParams.get("key") ?? "";
    if (!safeEqual(given, accessKey())) return notFound();
    const home = request.nextUrl.clone();
    home.pathname = "/";
    home.search = "";
    const res = NextResponse.redirect(home);
    res.cookies.set(DEVICE_COOKIE_NAME, await deviceToken(), { httpOnly: true, secure: true, sameSite: "strict", path: "/", maxAge: DEVICE_MAX_AGE });
    res.headers.set("Referrer-Policy", "no-referrer");
    return res;
  }

  const device = request.cookies.get(DEVICE_COOKIE_NAME)?.value;
  if (!(await deviceAllowed(device))) return notFound();

  let response = NextResponse.next({ request });
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  const key = (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY)!;
  const supabase = createServerClient(url, key, {
    cookieOptions: DEVICE_COOKIE,
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });
  const { data } = await supabase.auth.getUser();
  if (!data.user) {
    try {
      await mintOwnerSession(supabase);
    } catch {
      return new NextResponse("Solvant is temporarily unavailable (owner session could not be created).", { status: 503, headers: { "Cache-Control": "no-store" } });
    }
  }
  // keep the device cookie alive (rolling ~400 days)
  response.cookies.set(DEVICE_COOKIE_NAME, device!, { httpOnly: true, secure: true, sameSite: "strict", path: "/", maxAge: DEVICE_MAX_AGE });
  return response;
}

/** Creates a normal Supabase session for the workspace owner (the single admin member) without any visible step:
 *  the secret key generates a one-time sign-in token server-side (no e-mail is sent) and it is verified immediately. */
async function mintOwnerSession(supabase: ReturnType<typeof createServerClient>) {
  const admin = createSupabaseClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false },
    db: { schema: "solvant" },
  });
  const { data: owner, error: ownerErr } = await admin.from("members").select("user_id").eq("role", "admin").order("created_at").limit(1).maybeSingle();
  if (ownerErr || !owner) throw new Error("no owner");
  const { data: u, error: userErr } = await admin.auth.admin.getUserById(owner.user_id);
  if (userErr || !u.user?.email) throw new Error("owner user missing");
  const { data: link, error: linkErr } = await admin.auth.admin.generateLink({ type: "magiclink", email: u.user.email });
  if (linkErr || !link.properties?.hashed_token) throw new Error("token");
  const { error } = await supabase.auth.verifyOtp({ type: "magiclink", token_hash: link.properties.hashed_token });
  if (error) throw error;
}

export const config = {
  // everything except static build assets; /api/engine/* Python functions enforce the same device check themselves
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/engine).*)"],
};
