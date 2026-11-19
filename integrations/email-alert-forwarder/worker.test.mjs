// node --test integrations/email-alert-forwarder/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker, { senderAllowed, allowList, DEFAULT_SENDERS } from "./worker.js";

function msg(from, body = "Subject: New job\r\n\r\nhttps://www.upwork.com/jobs/~01abc", size) {
  const calls = { reject: null, forward: null };
  return {
    calls,
    from, rawSize: size ?? body.length,
    raw: new Blob([body]).stream(),
    setReject(r) { calls.reject = r; },
    async forward(to) { calls.forward = to; },
  };
}

test("sender allow-list matches platform domains, subdomains and exact addresses only", () => {
  assert.ok(senderAllowed("donotreply@upwork.com", DEFAULT_SENDERS));
  assert.ok(senderAllowed("alerts@mail.freelancer.com", DEFAULT_SENDERS));
  assert.ok(!senderAllowed("x@upwork.com.evil.io", DEFAULT_SENDERS));
  assert.ok(!senderAllowed("x@notupwork.com", DEFAULT_SENDERS));
  assert.ok(senderAllowed("me@example.com", ["me@example.com"]));
  assert.ok(!senderAllowed("other@example.com", ["me@example.com"]));
  assert.deepEqual(allowList({ ALLOWED_SENDERS: "" }), DEFAULT_SENDERS);
});

test("unconfigured or unknown sender is rejected and nothing is posted", async () => {
  let posted = 0;
  globalThis.fetch = async () => { posted++; return { ok: true }; };
  const m1 = msg("donotreply@upwork.com");
  await worker.email(m1, {}, {});
  assert.equal(m1.calls.reject, "forwarder not configured");
  const m2 = msg("spam@evil.io");
  await worker.email(m2, { SIGNAL_TOKEN: "t".repeat(40), ENDPOINT: "https://x/api" }, {});
  assert.equal(m2.calls.reject, "sender not accepted");
  assert.equal(posted, 0);
});

test("allowed alert is posted raw with the token header; failure falls back to forwarding", async () => {
  let seen;
  globalThis.fetch = async (url, init) => { seen = { url, init }; return { ok: false }; };
  const m = msg("donotreply@upwork.com");
  await worker.email(m, { SIGNAL_TOKEN: "t".repeat(40), ENDPOINT: "https://x/api", FALLBACK_TO: "me@example.com" }, {});
  assert.equal(seen.url, "https://x/api");
  assert.equal(seen.init.headers["content-type"], "message/rfc822");
  assert.equal(seen.init.headers["x-signal-token"], "t".repeat(40));
  assert.match(Buffer.from(seen.init.body).toString(), /upwork\.com\/jobs/);
  assert.equal(m.calls.forward, "me@example.com");
});

test("oversized messages are rejected", async () => {
  const m = msg("donotreply@upwork.com", "x", 3_000_000);
  await worker.email(m, { SIGNAL_TOKEN: "t".repeat(40), ENDPOINT: "https://x/api" }, {});
  assert.equal(m.calls.reject, "message too large");
});
