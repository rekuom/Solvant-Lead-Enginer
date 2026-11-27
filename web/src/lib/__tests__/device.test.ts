import { afterEach, describe, expect, it, vi } from "vitest";
import { deviceCookieValue, hostAllowed, safeEqual, signOAuthState, verifiedDeviceId, verifyOAuthState } from "../server/device";

const SECRET = "sb_secret_test_value_for_unit_tests_only";
const DEV = "11111111-2222-4333-8444-555555555555";

afterEach(() => vi.unstubAllEnvs());

describe("private device access", () => {
  it("accepts only a correctly signed device cookie", async () => {
    const v = await deviceCookieValue(DEV, SECRET);
    expect(v.startsWith(`${DEV}.`)).toBe(true);
    expect(await verifiedDeviceId(v, SECRET)).toBe(DEV);
    expect(await verifiedDeviceId(v, SECRET + "x")).toBeNull();                     // rotating the secret revokes every device
    expect(await verifiedDeviceId(v.replace(DEV, "11111111-2222-4333-8444-555555555556"), SECRET)).toBeNull();   // id swap
    expect(await verifiedDeviceId(undefined, SECRET)).toBeNull();
    expect(await verifiedDeviceId("garbage", SECRET)).toBeNull();
  });
  it("matches the Python engine's signature (same cookie works for both)", async () => {
    expect(await deviceCookieValue(DEV, SECRET)).toBe(`${DEV}.a03450dbacf447fe394756b624c555cda6d0ef70a2dcbc8a140d19b4f0dab87d`);
  });
  it("blocks alternative Vercel URLs", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SOLVANT_PUBLIC_HOST", "solvant-lead-enginer-web-i2ae.vercel.app");
    expect(hostAllowed("solvant-lead-enginer-web-i2ae.vercel.app")).toBe(true);
    expect(hostAllowed("solvant-lead-enginer-web-i2ae-git-main-rekuo.vercel.app")).toBe(false);
    expect(hostAllowed(null)).toBe(false);
  });
  it("binds the OAuth state cookie to the returned state and the starting device", async () => {
    const c = await signOAuthState("st4te", "v3rifier", DEV, SECRET);
    expect(await verifyOAuthState(c, "st4te", SECRET)).toEqual({ verifier: "v3rifier", deviceId: DEV });
    expect(await verifyOAuthState(c, "other", SECRET)).toBeNull();                   // state mismatch (CSRF / mix-up)
    expect(await verifyOAuthState(c.replace("v3rifier", "attacker"), "st4te", SECRET)).toBeNull();   // forged verifier
    expect(await verifyOAuthState(undefined, "st4te", SECRET)).toBeNull();
  });
  it("compares in constant time", () => {
    expect(safeEqual("abc", "abc")).toBe(true);
    expect(safeEqual("abc", "abd")).toBe(false);
  });
});
