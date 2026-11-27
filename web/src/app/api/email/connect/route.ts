import { createHash, randomBytes } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { authorizeUrl, microsoftConfigured } from "@/lib/server/microsoft";

/** Starts Microsoft OAuth (the device check already ran in the proxy). State + PKCE verifier live in a short httpOnly cookie. */
export async function GET(request: NextRequest) {
  if (!microsoftConfigured()) return NextResponse.redirect(new URL("/outreach?error=not_configured", request.url));
  const host = request.headers.get("host")!;
  const state = randomBytes(24).toString("base64url");
  const verifier = randomBytes(48).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const res = NextResponse.redirect(authorizeUrl(host, state, challenge));
  res.cookies.set("ms_oauth", `${state}.${verifier}`, { httpOnly: true, secure: true, sameSite: "lax", path: "/api/email", maxAge: 600 });
  return res;
}
