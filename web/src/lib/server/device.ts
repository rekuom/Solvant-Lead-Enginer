/** Private-tool access without a login screen.
 *
 * The site is only served to a device holding the `solvant_device` cookie: an HMAC of the server-side SOLVANT_ACCESS_KEY.
 * The cookie is set once by opening /setup?key=<SOLVANT_ACCESS_KEY> on the device (httpOnly, Secure, SameSite=Strict,
 * ~400 days, renewed on every visit). Every other request gets a plain 404 — there is no login page to find.
 * Requests on any host other than the production domain also get 404 (preview/alternative Vercel URLs are blocked).
 * Works in both the Next.js proxy (Web Crypto) and route handlers. */
export const DEVICE_COOKIE_NAME = "solvant_device";
export const DEVICE_MAX_AGE = 60 * 60 * 24 * 400;
const DEFAULT_HOST = "solvant-lead-enginer-web-i2ae.vercel.app";

export function accessKey(): string {
  return process.env.SOLVANT_ACCESS_KEY ?? "";
}

export function allowedHosts(): string[] {
  const configured = (process.env.SOLVANT_PUBLIC_HOST ?? DEFAULT_HOST).split(",").map((h) => h.trim().toLowerCase()).filter(Boolean);
  return process.env.NODE_ENV === "production" ? configured : [...configured, "localhost:3000", "127.0.0.1:3000"];
}

export function hostAllowed(host: string | null): boolean {
  return !!host && allowedHosts().includes(host.toLowerCase());
}

async function hmacHex(key: string, msg: string): Promise<string> {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** The cookie value for this deployment's access key (changes if the key is rotated, which revokes every device). */
export async function deviceToken(key = accessKey()): Promise<string> {
  return key.length >= 24 ? hmacHex(key, "solvant-device-v1") : "";
}

export function safeEqual(a: string, b: string): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function deviceAllowed(cookieValue: string | undefined, key = accessKey()): Promise<boolean> {
  const expected = await deviceToken(key);
  return !!expected && safeEqual(cookieValue ?? "", expected);
}

/** Setup is complete only when both server-side secrets exist. */
export function configured(): boolean {
  return accessKey().length >= 24 && !!process.env.SUPABASE_SECRET_KEY;
}
