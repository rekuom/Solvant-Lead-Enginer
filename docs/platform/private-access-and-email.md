# Private access (no login) and Outlook e-mail

## How access works
- There is no login, password, e-mailed link or device page.
- The site serves pages only to your own devices. They carry an httpOnly cookie that is an HMAC of the server-side `SOLVANT_ACCESS_KEY`.
- Every other visitor gets a plain **404 Not found**. This covers every page, `/api/*` route, Python engine endpoint and e-mail action.
- Any address other than the production domain also gets 404, so preview and other `*.vercel.app` deployment URLs are unusable.
- For an authorised device, the server creates the owner's normal Supabase session behind the scenes, using `SUPABASE_SECRET_KEY` (server-only). Every database query still runs as the owner under row-level security.
- The secret key is used for just three things, all on the server: creating that session, storing the encrypted mailbox token, and logging sent e-mail.
- Nothing is made public: anonymous database access stays blocked, and no secret reaches the browser.
- The machine endpoint `/api/engine/inbound-email` keeps its own revocable token.

## One-time setup (single screen in Vercel, then one visit per device)

**1. Add these environment variables.** In Vercel → your project → Settings → Environment Variables, choose Production:

| Variable | Value |
|---|---|
| `SOLVANT_ACCESS_KEY` | A long random phrase you choose, 24 characters or more. Keep it private. |
| `SUPABASE_SECRET_KEY` | Supabase → Project Settings → API Keys → **Secret key** (`sb_secret_…`). |
| `MICROSOFT_CLIENT_ID` | From step 2 below. |
| `MICROSOFT_CLIENT_SECRET` | From step 2 below. |
| `SOLVANT_PUBLIC_HOST` (optional) | Your custom domain, if you add one. It defaults to `solvant-lead-enginer-web-i2ae.vercel.app`. |

**2. Register the Microsoft app** (free, about 3 minutes):
1. Go to entra.microsoft.com → App registrations → New registration.
2. Fill in:
   - **Name:** Solvant Lead Engine
   - **Supported account types:** "Accounts in any organizational directory and personal Microsoft accounts" (this covers Outlook.com, Live and Hotmail)
   - **Redirect URI:** Web → `https://solvant-lead-enginer-web-i2ae.vercel.app/api/email/callback`
3. Copy the **Application (client) ID** into `MICROSOFT_CLIENT_ID`.
4. Go to Certificates & secrets → New client secret, and copy its **Value** into `MICROSOFT_CLIENT_SECRET`.

**3. Redeploy** in Vercel → Deployments → ⋯ → Redeploy.

**4. Open the setup link once on each of your devices:** `https://solvant-lead-enginer-web-i2ae.vercel.app/setup?key=YOUR_ACCESS_KEY`. You'll land straight on the dashboard. From then on, just open the site: the cookie lasts about 400 days and renews on every visit.

**5. Connect your mailbox:** go to Outreach → **Connect Outlook** and approve Microsoft's consent screen once.

To remove a device, use Settings → "Remove access from this device". To revoke every device at once, change `SOLVANT_ACCESS_KEY` and redeploy. This also disconnects the mailbox, because the token key is derived from it.

## Sending e-mail
1. Open a lead and use **Compose e-mail**:
   - the recipient is filled in automatically when the lead has a business e-mail with permission "invited" or "published for business";
   - the latest proposal draft is inserted;
   - edit the subject and message as you like.
2. Click **Send**. One real e-mail goes from your mailbox (a copy is saved in Sent Items), and then:
   - the lead moves to *Contacted*;
   - an activity is logged;
   - an inserted proposal draft is marked *submitted*, because it genuinely was.
3. **What is blocked:**
   - marketplace projects (the platform rules require in-platform contact);
   - do-not-contact entries;
   - addresses you typed yourself, until you confirm the buyer published the address or invited contact.
4. **Outreach page:**
   - shows the connected mailbox and every sent or failed e-mail with its error;
   - **Check replies & bounces** reads your inbox for replies from each recipient (the lead moves to *Replied*) and for non-delivery reports (marked *Bounced*).
