import { createServerClient } from "@supabase/ssr";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { DEVICE_COOKIE } from "@/lib/supabase/cookies";
import {
  DEVICE_COOKIE_NAME, DEVICE_MAX_AGE, OAUTH_COOKIE_NAME, configured, deviceCookieValue, hostAllowed, verifiedDeviceId, verifyOAuthState,
} from "@/lib/server/device";

/** Private-tool gate. No login screen anywhere.
 *  1. Any host other than the production domain → 404 (alternative/preview Vercel URLs are unusable).
 *  2. /setup/<one-time code> → registers this device (code single-use, 15 min, stored hashed) and opens the dashboard.
 *  3. A top-level navigation arriving from another site (link in an e-mail, Microsoft's redirect…) doesn't carry the
 *     SameSite=Strict device cookie; it gets a tiny same-site re-navigation page, after which the cookie is sent.
 *  4. /api/email/callback only: allowed without the device cookie when the signed OAuth state cookie (issued to an
 *     authorised device by /api/email/connect) matches the returned state; the handler then requires the PKCE verifier.
 *  5. Everything else without a valid, unrevoked device cookie → plain 404.
 *  6. An authorised device gets the owner's Supabase session automatically, so every query runs as the owner under RLS. */
const notFound = () => new NextResponse("Not found", { status: 404, headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex" } });
const STRICT = { httpOnly: true, secure: true, sameSite: "strict" as const, path: "/", maxAge: DEVICE_MAX_AGE };

function admin() {
  return createSupabaseClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false }, db: { schema: "solvant" },
  });
}

// revocation check, cached briefly per server instance
const activeCache = new Map<string, { ok: boolean; at: number }>();
async function deviceActive(id: string): Promise<boolean> {
  const hit = activeCache.get(id);
  if (hit && Date.now() - hit.at < 60_000) return hit.ok;
  const { data, error } = await admin().rpc("device_active", { p_device: id });
  const ok = !error && data === true;
  activeCache.set(id, { ok, at: Date.now() });
  return ok;
}

function bouncePage(request: NextRequest) {
  const target = request.nextUrl.pathname + request.nextUrl.search;
  const safe = target.replace(/[^A-Za-z0-9/?=&%._~+-]/g, "");
  return new NextResponse(
    `<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><meta http-equiv="refresh" content="0;url=${safe}"><title>…</title>`,
    { status: 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } },
  );
}

export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (!hostAllowed(request.headers.get("host"))) return notFound();

  if (!configured()) {
    if (path === "/setup-required") return NextResponse.next();
    const r = request.nextUrl.clone();
    r.pathname = "/setup-required";
    r.search = "";
    return NextResponse.redirect(r);
  }

  if (path.startsWith("/setup/")) {
    const code = path.slice("/setup/".length);
    if (!/^[0-9a-f]{64}$/.test(code)) return notFound();
    const ua = (request.headers.get("user-agent") ?? "").slice(0, 100);
    const { data: deviceId, error } = await admin().rpc("redeem_device_setup_code", { p_code: code, p_label: ua || null });
    if (error || !deviceId) return notFound();
    const res = new NextResponse(
      `<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><meta http-equiv="refresh" content="0;url=/"><title>Device ready</title><p>This device is set up. Opening your dashboard…</p>`,
      { status: 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } },
    );
    res.cookies.set(DEVICE_COOKIE_NAME, await deviceCookieValue(String(deviceId)), STRICT);
    return res;
  }

  const cookie = request.cookies.get(DEVICE_COOKIE_NAME)?.value;
  const deviceId = await verifiedDeviceId(cookie);
  const authorised = !!deviceId && (await deviceActive(deviceId));

  if (!authorised) {
    if (path === "/api/email/callback" && request.method === "GET") {
      const oauth = await verifyOAuthState(request.cookies.get(OAUTH_COOKIE_NAME)?.value, request.nextUrl.searchParams.get("state"));
      if (oauth && (await deviceActive(oauth.deviceId))) return NextResponse.next();   // handler re-verifies state and uses the PKCE verifier
      return notFound();
    }
    const crossSiteNavigation = request.method === "GET" && request.headers.get("sec-fetch-site") === "cross-site"
      && request.headers.get("sec-fetch-mode") === "navigate";
    if (crossSiteNavigation && !cookie) return bouncePage(request);
    return notFound();
  }

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
  response.cookies.set(DEVICE_COOKIE_NAME, cookie!, STRICT);   // rolling ~400 days
  return response;
}

/** Creates a normal Supabase session for the workspace owner (the single admin member) without any visible step:
 *  the secret key generates a one-time sign-in token server-side (no e-mail is sent) and it is verified immediately. */
async function mintOwnerSession(supabase: ReturnType<typeof createServerClient>) {
  const a = admin();
  const { data: owner, error: ownerErr } = await a.from("members").select("user_id").eq("role", "admin").order("created_at").limit(1).maybeSingle();
  if (ownerErr || !owner) throw new Error("no owner");
  const { data: u, error: userErr } = await a.auth.admin.getUserById(owner.user_id);
  if (userErr || !u.user?.email) throw new Error("owner user missing");
  const { data: link, error: linkErr } = await a.auth.admin.generateLink({ type: "magiclink", email: u.user.email });
  if (linkErr || !link.properties?.hashed_token) throw new Error("token");
  const { error } = await supabase.auth.verifyOtp({ type: "magiclink", token_hash: link.properties.hashed_token });
  if (error) throw error;
}

export const config = {
  // everything except static build assets; /api/engine/* Python functions enforce the same device check themselves
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/engine).*)"],
};
