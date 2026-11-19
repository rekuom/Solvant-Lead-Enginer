# Account activation: the steps only the owner can do

Everything below is already built, tested and deployed. Each feed prints "NOT CONFIGURED" and is skipped until its step is done. Nothing here costs money. No credential ever goes into the repository, chat, logs or GitHub.

## 1. Freelancer.com official API (marketplace projects, pipeline B)

1. Sign in to Freelancer.com and open the developer portal: developers.freelancer.com, then **My Apps → Create app**.
   - Use a name such as "Solvant Discovery" and a description such as "read-only project search for my own bidding".
   - Choose only the scopes needed to **read projects**. No bidding or messaging scopes are needed.
2. Generate an **OAuth access token** for your own account. The portal offers a personal token for your app.
3. Save the token as a **network secret** in the Claude environment **Rekuo**: claude.ai/code → environment settings → Network secrets → Add.
   - Host: `www.freelancer.com`
   - Header: `Freelancer-OAuth-V1`
   - Value: the token

   The secure in-chat form cannot save this header name, so it has to be added in settings. Saving a secret for a host also allows that host.
4. That's all. The daily task runs `freelancer_feed` automatically from the next run.

Terms: use is read-only and for your own bidding. Bids and messages happen on Freelancer.com, by you. Nothing is resold or exported.

## 2. TheirStack (employment signals from small companies, pipeline F)

1. Create a free account at theirstack.com. The free plan gives 200 credits a month; **do not add a card**.
2. Copy the API key from the account's API settings.
3. Tell Claude "save the TheirStack key". Claude opens the secure form, which stores the key as `Authorization: Bearer …` for `api.theirstack.com`. Or add it yourself under Network secrets.

Cost guard: each run takes at most 6 credits, and the code hard-caps any run at 8. At one run a day that is at most about 186 credits a month, inside the free plan. If credits run out, the API refuses and the feed reports "not configured". It cannot spend money.

## 3. Marketplace alert e-mails (Upwork, PeoplePerHour, Malt, Freelancer, freelancermap, Codeur → pipeline B)

You need a domain whose DNS is on Cloudflare (the free plan is enough).

1. **Create the token.** In Solvant (the live site) → Settings → Ingest tokens, create a token with scope **Inbound e-mail webhook**. Copy it once.
2. **Deploy the forwarder.** On your computer, from the repository:

   ```bash
   cd integrations/email-alert-forwarder
   ```

   ```bash
   npx wrangler login
   ```

   ```bash
   npx wrangler deploy
   ```

   ```bash
   npx wrangler secret put SIGNAL_TOKEN
   ```

   Paste the token when prompted.
3. **Route the e-mail.** In Cloudflare dashboard → your domain → Email → Email Routing:
   - enable it (Cloudflare adds the MX records);
   - create a custom address, e.g. `leads@your-domain`;
   - set the action to **Send to a Worker** → `solvant-alert-forwarder`.
4. **Point the alerts at that address.**
   - Directly: in each platform's notification settings, set saved-search or job alerts to send to `leads@your-domain`, where the platform allows another address.
   - Or forward them: in Gmail or Outlook, set a filter on alert e-mails that forwards them to `leads@your-domain`. Then add your own mailbox address to `ALLOWED_SENDERS` in `wrangler.toml` and run `npx wrangler deploy` again.
5. Optional: set `FALLBACK_TO` to a Cloudflare-verified address, so alerts still reach you if the engine is down.

Security: only mail from the listed platform domains, or your own address, is accepted. Everything else is rejected. The token sits in Cloudflare's secret store.

## 4. Optional

- **Upwork API.** Apply for an API key at upwork.com/developer. Approval is manual and can take weeks. Until then, Upwork arrives through alert e-mails (step 3).
- **Vercel connector.** Reconnect the Vercel connector in claude.ai to the new Vercel account, so Claude can read deployment logs directly.
- **Supabase Management API token.** Save a valid `sbp_` personal access token as the network secret for `api.supabase.com`, so Claude can run admin checks without the migration workflow. The current one is rejected (401).
- **Vercel plan.** The Hobby plan is for non-commercial use. Move to Vercel Pro before using the dashboard commercially. This is a paid step and needs your approval.
