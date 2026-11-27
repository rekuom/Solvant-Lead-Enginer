// Local stand-ins for the browser redirect-flow test: Supabase (auth admin + REST) on :4601 and the Microsoft identity
// platform + Graph on :4602 (a different site from localhost, so Microsoft's redirect back is genuinely cross-site).
import http from "node:http";
import crypto from "node:crypto";

export const OWNER = { id: "00000000-0000-4000-8000-0000000000aa", email: "owner@example.invalid" };
export const DEVICE_CODE = "a".repeat(64);
export const DEVICE_ID = "11111111-2222-4333-8444-555555555555";
const state = { mail: [], authorizeChallenge: null, pkceVerified: false, tokenCalls: 0, devices: new Set() };
export const observed = state;

const json = (res, code, body, headers = {}) => { res.writeHead(code, { "Content-Type": "application/json", ...headers }); res.end(JSON.stringify(body)); };
const readBody = (req) => new Promise((r) => { let b = ""; req.on("data", (c) => (b += c)); req.on("end", () => r(b)); });

export function startSupabase(port = 4601) {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    const body = await readBody(req);
    const p = url.pathname;
    const session = { access_token: "owner-access-token", refresh_token: "owner-refresh", token_type: "bearer", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: OWNER.id, email: OWNER.email, aud: "authenticated", role: "authenticated" } };
    if (p === "/auth/v1/user") return (req.headers.authorization || "").includes("owner-access-token") ? json(res, 200, session.user) : json(res, 401, { msg: "no session" });
    if (p.startsWith("/auth/v1/admin/users/")) return json(res, 200, { id: OWNER.id, email: OWNER.email });
    if (p === "/auth/v1/admin/generate_link") return json(res, 200, { hashed_token: "owner-hashed-token", action_link: "x", email_otp: "000000", redirect_to: "", verification_type: "magiclink", id: OWNER.id, email: OWNER.email });
    if (p === "/auth/v1/verify") return json(res, 200, session);
    if (p === "/auth/v1/token") return json(res, 200, session);
    if (p === "/rest/v1/rpc/redeem_device_setup_code") {
      const { p_code } = JSON.parse(body || "{}");
      if (p_code === DEVICE_CODE && !state.devices.has(DEVICE_ID)) { state.devices.add(DEVICE_ID); return json(res, 200, DEVICE_ID); }
      return json(res, 200, null);
    }
    if (p === "/rest/v1/rpc/device_active") return json(res, 200, state.devices.has(JSON.parse(body || "{}").p_device));
    if (p === "/rest/v1/rpc/my_role") return json(res, 200, "admin");
    if (p.startsWith("/rest/v1/rpc/")) return json(res, 200, p.endsWith("refresh_my_notifications") ? 0 : p.endsWith("dashboard_counts") || p.endsWith("sales_funnel") ? {} : []);
    if (p === "/rest/v1/members") return single(req, res, [{ user_id: OWNER.id }]);
    if (p === "/rest/v1/mail_accounts") {
      if (req.method === "POST") { const row = JSON.parse(body); state.mail = [{ ...(Array.isArray(row) ? row[0] : row) }]; return json(res, 201, state.mail); }
      if (req.method === "PATCH") return json(res, 200, []);
      return single(req, res, state.mail.map(({ refresh_token_enc, ...r }) => r));
    }
    if (p.startsWith("/rest/v1/")) return single(req, res, []);
    json(res, 404, { msg: "not faked" });
  }).listen(port);
}

function single(req, res, rows) {
  if ((req.headers.accept || "").includes("vnd.pgrst.object")) {
    return rows.length ? json(res, 200, rows[0]) : json(res, 406, { code: "PGRST116", message: "no rows" });
  }
  return json(res, 200, rows);
}

export function startMicrosoft(port = 4602, appOrigin = "http://localhost:3100") {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    const body = await readBody(req);
    if (url.pathname === "/oauth/authorize") {
      state.authorizeChallenge = url.searchParams.get("code_challenge");
      const back = new URL(url.searchParams.get("redirect_uri"));
      if (back.origin !== appOrigin) return json(res, 400, { error: "redirect_uri mismatch" });
      back.searchParams.set("code", "auth-code-123");
      back.searchParams.set("state", url.searchParams.get("state"));
      // like Microsoft: a consent page on the identity provider's own site; the user's click starts the navigation back,
      // so the return to Solvant is a genuinely cross-site top-level navigation (Strict cookies are withheld)
      res.writeHead(200, { "Content-Type": "text/html" });
      return res.end(`<!doctype html><title>Sign in to your account</title><p>Solvant Lead Engine wants to send mail as you.</p>
        <form method="get" action="/oauth/consent"><input type="hidden" name="to" value="${back.toString().replace(/"/g, "&quot;")}"><button id="accept">Accept</button></form>`);
    }
    if (url.pathname === "/oauth/consent") {
      res.writeHead(302, { Location: url.searchParams.get("to") });   // Microsoft's redirect back after consent
      return res.end();
    }
    if (url.pathname === "/oauth/token") {
      state.tokenCalls++;
      const f = new URLSearchParams(body);
      const ok = f.get("code") === "auth-code-123" && crypto.createHash("sha256").update(f.get("code_verifier") || "").digest("base64url") === state.authorizeChallenge;
      state.pkceVerified = ok;
      return ok ? json(res, 200, { access_token: "graph-token", refresh_token: "ms-refresh-token", expires_in: 3600, scope: "Mail.Send Mail.Read User.Read offline_access" })
                : json(res, 400, { error: "invalid_grant", error_description: "PKCE verification failed" });
    }
    if (url.pathname === "/graph/me") return json(res, 200, { displayName: "Owner", mail: "owner@live.example.invalid" });
    json(res, 404, {});
  }).listen(port);
}
