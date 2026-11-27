import { createHash, randomBytes } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { authorizeUrl, microsoftConfigured } from "@/lib/server/microsoft";
import { DEVICE_COOKIE_NAME, OAUTH_COOKIE_NAME, signOAuthState, verifiedDeviceId } from "@/lib/server/device";

/** Starts Microsoft OAuth from an authorised device (the proxy already checked it). The state + PKCE verifier are kept in
 *  a short-lived httpOnly cookie, signed and bound to this device, so only this flow can complete on the callback. */
export async function GET(request: NextRequest) {
  if (!microsoftConfigured()) return NextResponse.redirect(new URL("/outreach?error=not_configured", request.url));
  const deviceId = await verifiedDeviceId(request.cookies.get(DEVICE_COOKIE_NAME)?.value);
  if (!deviceId) return new NextResponse("Not found", { status: 404 });
  const origin = new URL(request.url).origin;
  const state = randomBytes(24).toString("base64url");
  const verifier = randomBytes(48).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const res = NextResponse.redirect(authorizeUrl(origin, state, challenge));
  // SameSite=Lax: sent on Microsoft's top-level redirect back to us; scoped to the e-mail routes; 10 minutes
  res.cookies.set(OAUTH_COOKIE_NAME, await signOAuthState(state, verifier, deviceId), { httpOnly: true, secure: true, sameSite: "lax", path: "/api/email", maxAge: 600 });
  return res;
}
