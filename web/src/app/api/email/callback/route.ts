import { NextResponse, type NextRequest } from "next/server";
import { adminClient } from "@/lib/server/admin";
import { exchangeCode, me, SCOPES } from "@/lib/server/microsoft";
import { OAUTH_COOKIE_NAME, verifyOAuthState } from "@/lib/server/device";
import { encryptToken } from "@/lib/server/token-crypto";

/** Microsoft redirects here after consent: verify the device-bound state, redeem the code with the PKCE verifier, store the
 *  refresh token encrypted. The redirect back to /outreach passes through the proxy's same-site re-navigation. */
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const back = (q: string) => {
    const res = NextResponse.redirect(new URL(`/outreach?${q}`, request.url));
    res.cookies.set(OAUTH_COOKIE_NAME, "", { path: "/api/email", maxAge: 0 });
    return res;
  };
  if (url.searchParams.get("error")) return back("error=consent_declined");
  // state must match the signed, device-bound cookie set by /api/email/connect; the code is only redeemable with its PKCE verifier
  const oauth = await verifyOAuthState(request.cookies.get(OAUTH_COOKIE_NAME)?.value, url.searchParams.get("state"));
  const code = url.searchParams.get("code");
  if (!code || !oauth) return back("error=invalid_state");
  try {
    const tokens = await exchangeCode(url.origin, code, oauth.verifier);
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
