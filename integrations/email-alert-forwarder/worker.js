// Solvant marketplace-alert forwarder: a Cloudflare Email Worker (free on Cloudflare's Workers free plan).
//
// Cloudflare Email Routing delivers mail sent to e.g. leads@<your-domain> to this Worker. The Worker passes the raw
// alert e-mail to the Solvant engine endpoint, which extracts the project links (Upwork, Freelancer, PeoplePerHour,
// Malt, freelancermap, Codeur, freelance.de ...), classifies them and files them as marketplace opportunities.
//
// Secrets/vars (never committed):  SIGNAL_TOKEN  — an ingest token with scope "inbound_email" (wrangler secret put)
//                                  ENDPOINT      — https://<your-site>/api/engine/inbound-email (wrangler.toml [vars])
//                                  ALLOWED_SENDERS — comma-separated sender addresses/domains accepted (wrangler.toml)
//                                  FALLBACK_TO   — optional verified address that receives the mail if the engine fails
// Only mail from allowed senders is processed; everything else is rejected, so the address cannot be used to inject leads.

export const DEFAULT_SENDERS = [
  "upwork.com", "freelancer.com", "peopleperhour.com", "malt.com", "malt.fr", "malt.de", "malt.co.uk", "malt.es", "malt.nl",
  "freelancermap.de", "codeur.com", "freelance.de", "gulp.de",
];
const MAX_BYTES = 2_000_000;

export function senderAllowed(from, allowList) {
  const addr = String(from || "").trim().toLowerCase();
  const at = addr.lastIndexOf("@");
  if (at < 1) return false;
  const domain = addr.slice(at + 1);
  return allowList.some((entry) => {
    const e = entry.trim().toLowerCase();
    if (!e) return false;
    if (e.includes("@")) return addr === e;                    // an exact address (e.g. your own forwarding mailbox)
    return domain === e || domain.endsWith("." + e);           // a platform domain or its subdomains (mail.upwork.com)
  });
}

export function allowList(env) {
  const extra = String(env.ALLOWED_SENDERS || "").split(",").map((s) => s.trim()).filter(Boolean);
  return extra.length ? extra : DEFAULT_SENDERS;
}

export default {
  async email(message, env, ctx) {
    if (!env.SIGNAL_TOKEN || !env.ENDPOINT) {
      message.setReject("forwarder not configured");
      return;
    }
    if (!senderAllowed(message.from, allowList(env))) {
      message.setReject("sender not accepted");
      return;
    }
    if (message.rawSize > MAX_BYTES) {
      message.setReject("message too large");
      return;
    }
    const raw = await new Response(message.raw).arrayBuffer();
    let ok = false;
    try {
      const res = await fetch(env.ENDPOINT, {
        method: "POST",
        headers: { "content-type": "message/rfc822", "x-signal-token": env.SIGNAL_TOKEN },
        body: raw,
      });
      ok = res.ok;
    } catch (_err) {
      ok = false;   // nothing about the message or token is logged
    }
    if (!ok && env.FALLBACK_TO) {
      await message.forward(env.FALLBACK_TO);   // keep the alert: it lands in your normal inbox instead
    }
  },
};
