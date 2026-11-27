// Real-browser test of the private-access + Microsoft OAuth redirect flow (Chromium via Playwright, production build).
// Usage: node e2e/oauth-flow.mjs   (expects `next start -p 3100` running with the env in e2e/run.sh)
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");   // preinstalled Playwright (CommonJS)
import { DEVICE_CODE, observed, startMicrosoft, startSupabase } from "./fake-services.mjs";

const APP = "http://localhost:3100";
let failures = 0;
const check = (ok, label, detail = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? " — " + detail : ""}`); if (!ok) failures++; };

startSupabase(4601);
startMicrosoft(4602, APP);
await new Promise((r) => setTimeout(r, 300));

const browser = await chromium.launch();
try {
  // --- unauthorised visitor -----------------------------------------------------------------------------------------
  const stranger = await browser.newContext();
  const sp = await stranger.newPage();
  let r = await sp.goto(`${APP}/`);
  check(r.status() === 404, "stranger: dashboard is 404 (no login page)", `HTTP ${r.status()}`);
  r = await sp.goto(`${APP}/api/email/callback?code=x&state=y`);
  check(r.status() === 404, "stranger: OAuth callback is 404 without a valid signed state cookie", `HTTP ${r.status()}`);
  await stranger.addCookies([{ name: "ms_oauth", value: "s.v.11111111-2222-4333-8444-555555555555.forged", url: `${APP}/api/email` }]);
  r = await sp.goto(`${APP}/api/email/callback?code=x&state=s`);
  check(r.status() === 404, "stranger: forged OAuth state cookie is 404", `HTTP ${r.status()}`);
  await sp.goto(`http://127.0.0.1:4602/oauth/authorize?redirect_uri=${encodeURIComponent(APP + "/outreach")}&state=z`);
  const outreachResponses = [];
  sp.on("response", (res) => { if (res.url().startsWith(`${APP}/outreach`)) outreachResponses.push(res.status()); });
  await sp.click("#accept");                                  // a link to Solvant from another site
  const blocked = await sp.waitForSelector("text=Not found", { timeout: 15000 }).then(() => true).catch(() => false);
  check(blocked && outreachResponses.length >= 2 && outreachResponses[0] === 200 && outreachResponses.at(-1) === 404,
        "stranger: cross-site link → same-site re-navigation → still 404", JSON.stringify(outreachResponses));
  await stranger.close();

  // --- owner device: one-time setup code ------------------------------------------------------------------------------
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  r = await page.goto(`${APP}/setup/${DEVICE_CODE}`);
  await page.waitForURL(`${APP}/`, { timeout: 15000 });
  const cookies = await ctx.cookies(APP);
  const dev = cookies.find((c) => c.name === "solvant_device");
  check(!!dev && dev.httpOnly && dev.sameSite === "Strict" && dev.secure, "setup code sets an httpOnly, Secure, SameSite=Strict device cookie");
  check(!cookies.some((c) => /key=/.test(c.value)), "no reusable secret in cookies");
  const history = await page.evaluate(() => location.href);
  check(!history.includes("/setup/"), "setup URL does not stay in the address bar");
  r = await page.goto(`${APP}/`);
  check(r.status() === 200, "owner device opens the dashboard directly", `HTTP ${r.status()}`);
  const p2 = await (await browser.newContext()).newPage();
  r = await p2.goto(`${APP}/setup/${DEVICE_CODE}`);
  check(r.status() === 404, "the same setup code cannot be used twice", `HTTP ${r.status()}`);

  // --- Microsoft OAuth, through the real cross-site redirect ----------------------------------------------------------
  r = await page.goto(`${APP}/outreach`);
  check(r.status() === 200 && (await page.content()).includes("Connect Outlook"), "Outreach page offers Connect Outlook");
  let callbackCookie = null;
  const seen = [];
  page.on("request", (req) => { if (req.url().includes("/api/email/callback")) seen.push(req.allHeaders().then((h) => { callbackCookie = h["cookie"] ?? ""; })); });
  await page.click("text=Connect Outlook");
  await page.waitForURL(/127\.0\.0\.1:4602\/oauth\/authorize/, { timeout: 15000 });
  await page.click("#accept");                         // consent on the identity provider's site
  await page.waitForURL(/\/outreach\?connected=1/, { timeout: 20000 });
  await Promise.all(seen);
  check(callbackCookie !== null && !callbackCookie.includes("solvant_device") && callbackCookie.includes("ms_oauth"),
        "Microsoft's cross-site redirect arrived WITHOUT the Strict device cookie, with the signed state cookie", JSON.stringify((callbackCookie || "").split("; ").map((c) => c.split("=")[0])));
  check(observed.pkceVerified, "code was redeemed only with the matching PKCE verifier");
  const landed = await page.waitForSelector("text=Mailbox connected", { timeout: 15000 }).then(() => true).catch(() => false);
  check(landed, "after the callback the owner lands on Outreach (connected) via the same-site re-navigation");
  check(observed.mail.length === 1 && String(observed.mail[0].refresh_token_enc || "").startsWith("v1:") && !JSON.stringify(observed.mail).includes("ms-refresh-token"),
        "mailbox token stored encrypted (plaintext never sent to the database)");
  const after = await ctx.cookies(`${APP}/api/email`);
  check(!after.some((c) => c.name === "ms_oauth" && c.value), "OAuth state cookie cleared after use");
  const replay = await page.goto(`${APP}/api/email/callback?code=auth-code-123&state=whatever`);
  check(replay.url().includes("error=invalid_state"), "replaying the callback fails (state no longer valid)");
} finally {
  await browser.close();
}
console.log(failures ? `\n${failures} FAILED` : "\nALL BROWSER FLOW CHECKS PASSED");
process.exit(failures ? 1 : 0);
