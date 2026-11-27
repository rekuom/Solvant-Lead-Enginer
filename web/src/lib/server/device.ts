/** Private-tool access without a login screen.
 *
 * Each of the owner's devices holds an httpOnly `solvant_device` cookie: "<device id>.<HMAC>", signed with a key derived
 * from the server-only SUPABASE_SECRET_KEY. A device is registered once by opening /setup/<one-time code> (single use,
 * 15 minutes, stored hashed); there is no reusable secret in any URL. Devices can be revoked individually.
 * Every request without a valid device cookie gets a plain 404; any host other than the production domain gets 404.
 * Runs in the Next.js proxy and in route handlers (Web Crypto only). */
export const DEVICE_COOKIE_NAME = "solvant_device";
export const OAUTH_COOKIE_NAME = "ms_oauth";
export const DEVICE_MAX_AGE = 60 * 60 * 24 * 400;
const DEFAULT_HOST = "solvant-lead-enginer-web-i2ae.vercel.app";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function serverSecret(): string {
  return process.env.SUPABASE_SECRET_KEY ?? "";
}

/** Setup is complete when the server-only secret exists (stage 1 needs nothing else). */
export function configured(): boolean {
  return serverSecret().length >= 20;
}

export function allowedHosts(): string[] {
  const configuredHosts = (process.env.SOLVANT_PUBLIC_HOST ?? DEFAULT_HOST).split(",").map((h) => h.trim().toLowerCase()).filter(Boolean);
  return process.env.NODE_ENV === "production" ? configuredHosts : [...configuredHosts, "localhost:3000", "127.0.0.1:3000"];
}

export function hostAllowed(host: string | null): boolean {
  return !!host && allowedHosts().includes(host.toLowerCase());
}

async function hmacHex(key: string, msg: string): Promise<string> {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function safeEqual(a: string, b: string): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

const signingKey = (secret: string) => `solvant-device-v2:${secret}`;

export async function deviceCookieValue(deviceId: string, secret = serverSecret()): Promise<string> {
  if (!UUID.test(deviceId) || secret.length < 20) return "";
  return `${deviceId}.${await hmacHex(signingKey(secret), `device:${deviceId}`)}`;
}

/** Returns the device id when the cookie carries a valid signature (revocation is checked separately). */
export async function verifiedDeviceId(cookieValue: string | undefined, secret = serverSecret()): Promise<string | null> {
  const [id, sig] = (cookieValue ?? "").split(".");
  if (!id || !sig || !UUID.test(id) || secret.length < 20) return null;
  return safeEqual(sig, await hmacHex(signingKey(secret), `device:${id}`)) ? id : null;
}

/** OAuth state cookie, bound to the authorised device that started the flow: state.verifier.deviceId.signature */
export async function signOAuthState(state: string, verifier: string, deviceId: string, secret = serverSecret()): Promise<string> {
  return `${state}.${verifier}.${deviceId}.${await hmacHex(signingKey(secret), `oauth:${state}:${verifier}:${deviceId}`)}`;
}

export async function verifyOAuthState(cookieValue: string | undefined, returnedState: string | null, secret = serverSecret()):
  Promise<{ verifier: string; deviceId: string } | null> {
  const [state, verifier, deviceId, sig] = (cookieValue ?? "").split(".");
  if (!state || !verifier || !deviceId || !sig || !returnedState || secret.length < 20) return null;
  if (!safeEqual(sig, await hmacHex(signingKey(secret), `oauth:${state}:${verifier}:${deviceId}`))) return null;
  if (!safeEqual(returnedState, state)) return null;
  return { verifier, deviceId };
}
