/** Trusted-device session cookie: persists ~400 days (the browser maximum) and is renewed on every visit by the proxy,
 *  so the owner's device stays signed in. Only the Supabase session lives here; no service credentials ever reach the browser. */
export const DEVICE_COOKIE = { maxAge: 60 * 60 * 24 * 400, sameSite: "lax" as const, secure: true, path: "/" };
