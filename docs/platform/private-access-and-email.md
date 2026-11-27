# Private access (no login) and Outlook e-mail

## How access works
- **No login of any kind.** Each of your devices holds an httpOnly, Secure, SameSite=Strict cookie, `<device id>.<signature>`. It is signed with a key derived from the server-only `SUPABASE_SECRET_KEY`.
- **Registering a device.** Open a one-time link, `/setup/<code>`, on the device:
  - the code works once and expires after 15 minutes;
  - it is stored only as a hash;
  - no reusable secret ever appears in a URL or in browser history.
- **Everyone else gets 404.** That covers every page, every `/api/*` route, the Python engine endpoints and the e-mail actions. Any host other than the production domain also gets 404.
- **Links from other sites.** A SameSite=Strict cookie is not sent when you arrive from a link in an e-mail, Teams, a search result or Microsoft's sign-in. Such a visit gets a tiny same-site re-navigation page, after which the cookie is sent. Visitors without the cookie still get 404.
- **Microsoft OAuth callback.** Only `/api/email/callback` may run without the device cookie, and only when both hold:
  - the request carries the short-lived, signed OAuth state cookie that `/api/email/connect` issued to an authorised device;
  - the cookie matches the returned `state`.

  The authorisation code can then be redeemed only with that flow's PKCE verifier.
- **Your data stays protected.** For an authorised device, the server creates the owner's normal Supabase session, so every query runs as the owner under row-level security. The database is never opened to anonymous users.
- **Devices** are listed in Settings, and each one can be revoked. Rotating `SUPABASE_SECRET_KEY` revokes every device and disconnects the mailbox.
- **Tests:** the real browser flow is covered by `web/e2e/run.sh` (Chromium, production build, with a stand-in identity provider on a different site).

## Stage 1: website access
1. Vercel → Project → Settings → Environment Variables → Production: add `SUPABASE_SECRET_KEY` (from Supabase → Project Settings → API Keys → Secret key). Then redeploy.
2. Open the one-time device link you are given on your computer. You land on the dashboard; from then on, just open the site.

To add another device, go to Settings → Devices with access → Create one-time link.

## Stage 2: Outlook e-mail (after stage 1 works)
1. Register the app at entra.microsoft.com → App registrations → New registration (free):
   - **Supported account types:** any organizational directory and personal Microsoft accounts;
   - **Redirect URI:** Web → `https://solvant-lead-enginer-web-i2ae.vercel.app/api/email/callback`;
   - then create a client secret.
2. In Vercel, add `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET`, then redeploy.
3. Go to Outreach → Connect Outlook and accept Microsoft's screen.
4. Send one test e-mail that you explicitly authorise, then check the sent log, and reply tracking with "Check replies & bounces".

## Sending e-mail
- **Compose:** each lead has a **Compose e-mail** section.
  - The recipient is filled in only from a business contact marked "invited" or "published for business".
  - The latest proposal draft is inserted. Edit the subject and message as you like.
- **Send:** one real e-mail goes from your mailbox (a copy is saved in Sent Items). Then:
  - the lead moves to *Contacted* and an activity is logged;
  - an inserted proposal draft is marked submitted.
- **What is blocked:**
  - marketplace projects (contact stays in-platform);
  - do-not-contact entries;
  - addresses you typed yourself, until you confirm the buyer published or invited them.
- **The Outreach page** lists sent and failed e-mails with their errors. "Check replies & bounces" detects replies (the lead moves to *Replied*) and non-delivery reports (marked *Bounced*).
