import "server-only";
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

/** AES-256-GCM for the mailbox refresh token at rest. The key is derived on the server from SOLVANT_ACCESS_KEY, so the
 *  database alone (or a database leak) never yields a usable mailbox token. Rotating the access key requires reconnecting. */
function key(): Buffer {
  const secret = process.env.SOLVANT_ACCESS_KEY ?? "";
  if (secret.length < 24) throw new Error("SOLVANT_ACCESS_KEY is not configured");
  return createHash("sha256").update(`solvant-mail-token-v1:${secret}`).digest();
}

export function encryptToken(plain: string): string {
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", key(), iv);
  const enc = Buffer.concat([c.update(plain, "utf8"), c.final()]);
  return `v1:${iv.toString("base64")}:${c.getAuthTag().toString("base64")}:${enc.toString("base64")}`;
}

export function decryptToken(stored: string): string {
  const [v, iv, tag, data] = stored.split(":");
  if (v !== "v1" || !iv || !tag || !data) throw new Error("unsupported token format");
  const d = createDecipheriv("aes-256-gcm", key(), Buffer.from(iv, "base64"));
  d.setAuthTag(Buffer.from(tag, "base64"));
  return Buffer.concat([d.update(Buffer.from(data, "base64")), d.final()]).toString("utf8");
}
