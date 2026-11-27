import "server-only";

/** Microsoft identity platform (OAuth 2.0 auth-code + PKCE, confidential client) and Microsoft Graph mail.
 *  Works with personal Outlook.com/Live/Hotmail accounts and work accounts (tenant "common").
 *  Scopes: send mail, read mail (to detect replies and bounce notices), basic profile, offline access (refresh token). */
export const SCOPES = ["offline_access", "User.Read", "Mail.Send", "Mail.Read"];
const tenant = () => process.env.MICROSOFT_TENANT || "common";
// overridable only so the redirect flow can be tested end to end against a local stand-in; production uses the defaults
const AUTH = () => process.env.MICROSOFT_AUTHORITY_URL || `https://login.microsoftonline.com/${tenant()}/oauth2/v2.0`;
const GRAPH_BASE = () => process.env.MICROSOFT_GRAPH_URL || "https://graph.microsoft.com/v1.0";

export function microsoftConfigured(): boolean {
  return !!process.env.MICROSOFT_CLIENT_ID && !!process.env.MICROSOFT_CLIENT_SECRET;
}

export function redirectUri(origin: string): string {
  return `${origin}/api/email/callback`;
}

export function authorizeUrl(origin: string, state: string, challenge: string): string {
  const q = new URLSearchParams({
    client_id: process.env.MICROSOFT_CLIENT_ID!, response_type: "code", redirect_uri: redirectUri(origin), response_mode: "query",
    scope: SCOPES.join(" "), state, code_challenge: challenge, code_challenge_method: "S256", prompt: "select_account",
  });
  return `${AUTH()}/authorize?${q}`;
}

type TokenSet = { access_token: string; refresh_token?: string; expires_in: number; scope?: string };

async function tokenRequest(body: Record<string, string>): Promise<TokenSet> {
  const res = await fetch(`${AUTH()}/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: process.env.MICROSOFT_CLIENT_ID!, client_secret: process.env.MICROSOFT_CLIENT_SECRET!, ...body }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`Microsoft sign-in failed: ${String(data.error_description || data.error || res.status).split("\r")[0].slice(0, 200)}`);
  return data as TokenSet;
}

export const exchangeCode = (origin: string, code: string, verifier: string) =>
  tokenRequest({ grant_type: "authorization_code", code, redirect_uri: redirectUri(origin), code_verifier: verifier, scope: SCOPES.join(" ") });

export const refreshAccess = (refreshToken: string) =>
  tokenRequest({ grant_type: "refresh_token", refresh_token: refreshToken, scope: SCOPES.join(" ") });

async function graph(accessToken: string, path: string, init?: RequestInit) {
  const res = await fetch(`${GRAPH_BASE()}${path}`, { ...init, headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (res.status === 202 || res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`Outlook: ${String(data?.error?.message || res.status).slice(0, 300)}`);
  return data;
}

export async function me(accessToken: string): Promise<{ email: string; name: string | null }> {
  const d = await graph(accessToken, "/me?$select=displayName,mail,userPrincipalName");
  return { email: String(d.mail || d.userPrincipalName || "").toLowerCase(), name: d.displayName ?? null };
}

export async function sendMail(accessToken: string, to: string, subject: string, body: string): Promise<void> {
  await graph(accessToken, "/me/sendMail", {
    method: "POST",
    body: JSON.stringify({ message: { subject, body: { contentType: "Text", content: body }, toRecipients: [{ emailAddress: { address: to } }] }, saveToSentItems: true }),
  });
}

/** Messages received since `since` from `from` (replies). */
export async function repliesFrom(accessToken: string, from: string, since: string): Promise<number> {
  const f = encodeURIComponent(`receivedDateTime ge ${since} and from/emailAddress/address eq '${from.replace(/'/g, "''")}'`);
  const d = await graph(accessToken, `/me/messages?$filter=${f}&$select=id&$top=5`);
  return Array.isArray(d?.value) ? d.value.length : 0;
}

/** Non-delivery reports received since `since` (subject starts "Undeliverable"/"Delivery has failed"). */
export async function bounceNotices(accessToken: string, since: string): Promise<{ subject: string; preview: string }[]> {
  const f = encodeURIComponent(`receivedDateTime ge ${since} and (startswith(subject,'Undeliverable') or startswith(subject,'Delivery has failed'))`);
  const d = await graph(accessToken, `/me/messages?$filter=${f}&$select=subject,bodyPreview&$top=50`);
  return (d?.value ?? []).map((m: { subject?: string; bodyPreview?: string }) => ({ subject: m.subject ?? "", preview: m.bodyPreview ?? "" }));
}
