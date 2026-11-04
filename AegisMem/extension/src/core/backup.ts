/** Password-encrypted backup files (PBKDF2-SHA256 600k → AES-256-GCM). Restorable on any device. */
import { b64, unb64, PBKDF2_ITERATIONS } from "./crypto";
import type { Conversation } from "./types";

export interface BackupFile {
  format: "aegismem-recall-backup";
  version: 1;
  salt: string;
  iterations: number;
  iv: string;
  ct: string;
}

async function keyFor(password: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

export async function encryptBackup(conversations: Conversation[], password: string, iterations = PBKDF2_ITERATIONS): Promise<BackupFile> {
  if (password.length < 10) throw new Error("Backup password must be at least 10 characters");
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new TextEncoder().encode(JSON.stringify({ conversations }));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await keyFor(password, salt, iterations), data));
  return { format: "aegismem-recall-backup", version: 1, salt: b64(salt), iterations, iv: b64(iv), ct: b64(ct) };
}

export async function decryptBackup(file: BackupFile, password: string): Promise<Conversation[]> {
  if (file?.format !== "aegismem-recall-backup") throw new Error("Not an AegisMem backup file");
  try {
    const key = await keyFor(password, unb64(file.salt), file.iterations);
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(file.iv) }, key, unb64(file.ct));
    return JSON.parse(new TextDecoder().decode(pt)).conversations;
  } catch {
    throw new Error("Wrong password or damaged backup file");
  }
}
