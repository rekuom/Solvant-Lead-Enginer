import { NextResponse, type NextRequest } from "next/server";
import { adminClient } from "@/lib/server/admin";
import { exchangeCode, me, SCOPES } from "@/lib/server/microsoft";
import { safeEqual } from "@/lib/server/device";
import { encryptToken } from "@/lib/server/token-crypto";

/** Microsoft redirects here after consent: verify state, exchange the code, store the refresh token encrypted. */
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const back = (q: string) => {
    const res = NextResponse.redirect(new URL(`/outreach?${q}`, request.url));
    res.cookies.set("ms_oauth", "", { path: "/api/email", maxAge: 0 });
    return res;
  };
  const [state, verifier] = (request.cookies.get("ms_oauth")?.value ?? "").split(".");
  if (url.searchParams.get("error")) return back("error=consent_declined");
  const code = url.searchParams.get("code");
  if (!code || !state || !verifier || !safeEqual(url.searchParams.get("state") ?? "", state)) return back("error=invalid_state");
  try {
    const tokens = await exchangeCode(request.headers.get("host")!, code, verifier);
    if (!tokens.refresh_token) return back("error=no_refresh_token");
    const who = await me(tokens.access_token);
    if (!who.email) return back("error=no_mailbox");
    const admin = adminClient();
    await admin.from("mail_accounts").update({ active: false }).neq("email", who.email);
    const { error } = await admin.from("mail_accounts").upsert({
      provider: "microsoft", email: who.email, display_name: who.name, refresh_token_enc: encryptToken(tokens.refresh_token),
      scopes: tokens.scope ?? SCOPES.join(" "), active: true, connected_at: new Date().toISOString(), last_error: null,
    }, { onConflict: "provider,email" });
    if (error) return back("error=store_failed");
    return back("connected=1");
  } catch {
    return back("error=exchange_failed");
  }
}
