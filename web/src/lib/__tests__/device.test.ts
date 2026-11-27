import { afterEach, describe, expect, it, vi } from "vitest";
import { deviceAllowed, deviceToken, hostAllowed, safeEqual } from "../server/device";

const KEY = "correct-horse-battery-staple-solvant-2026";

afterEach(() => vi.unstubAllEnvs());

describe("private device access", () => {
  it("accepts only the HMAC of the configured access key", async () => {
    const t = await deviceToken(KEY);
    expect(t).toMatch(/^[0-9a-f]{64}$/);
    expect(await deviceAllowed(t, KEY)).toBe(true);
    expect(await deviceAllowed(t, KEY + "x")).toBe(false);       // rotating the key revokes every device
    expect(await deviceAllowed(undefined, KEY)).toBe(false);
    expect(await deviceAllowed("", KEY)).toBe(false);
  });
  it("refuses everything when the key is missing or too short", async () => {
    expect(await deviceToken("short")).toBe("");
    expect(await deviceAllowed("", "short")).toBe(false);
  });
  it("matches the Python engine's HMAC (same cookie works for both)", async () => {
    // python: hmac.new(KEY, b"solvant-device-v1", sha256).hexdigest()
    expect(await deviceToken(KEY)).toBe("17a6e92056aa2773c5af804929684ee3e1546527f41503ec59f6be132437fda0");
  });
  it("blocks alternative Vercel URLs", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SOLVANT_PUBLIC_HOST", "solvant-lead-enginer-web-i2ae.vercel.app");
    expect(hostAllowed("solvant-lead-enginer-web-i2ae.vercel.app")).toBe(true);
    expect(hostAllowed("solvant-lead-enginer-web-i2ae-git-main-rekuo.vercel.app")).toBe(false);
    expect(hostAllowed("solvant-lead-enginer-abc123.vercel.app")).toBe(false);
    expect(hostAllowed(null)).toBe(false);
  });
  it("compares in constant time", () => {
    expect(safeEqual("abc", "abc")).toBe(true);
    expect(safeEqual("abc", "abd")).toBe(false);
    expect(safeEqual("abc", "abcd")).toBe(false);
  });
});
