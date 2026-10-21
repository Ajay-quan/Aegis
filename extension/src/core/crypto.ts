/**
 * Zero-knowledge encryption for local memory (WebCrypto only, no dependencies).
 *
 *   data key (DEK)   random AES-256-GCM key; encrypts every memory record
 *   passphrase KEK   PBKDF2-SHA256 (600k iterations, OWASP 2023) over the user's passphrase; wraps the DEK
 *   recovery KEK     random 256-bit recovery key shown once at setup; also wraps the DEK
 *
 * Only ciphertext, salts and wrapped keys are ever persisted. The passphrase and recovery key never
 * leave the device and are never stored. Losing both means the data cannot be recovered, by design.
 */

export const PBKDF2_ITERATIONS = 600_000;

export interface Sealed {
  iv: string; // base64
  ct: string; // base64
}

export interface KeyEnvelope {
  version: 1;
  salt: string;
  iterations: number;
  wrappedByPassphrase: Sealed;
  wrappedByRecovery: Sealed;
}

const enc = new TextEncoder();
const dec = new TextDecoder();

export function b64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export function unb64(s: string): Uint8Array {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

function random(n: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(n));
}

async function kekFromPassphrase(passphrase: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", enc.encode(passphrase), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

async function kekFromRecovery(recovery: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", recovery, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function sealBytes(key: CryptoKey, data: Uint8Array): Promise<Sealed> {
  const iv = random(12);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data));
  return { iv: b64(iv), ct: b64(ct) };
}

async function openBytes(key: CryptoKey, s: Sealed): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(s.iv) }, key, unb64(s.ct)));
}

async function importDek(raw: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

/** Recovery keys are shown to the user as groups of hex, e.g. "3f9a-…". */
export function formatRecoveryKey(k: Uint8Array): string {
  return Array.from(k, (b) => b.toString(16).padStart(2, "0")).join("").match(/.{8}/g)!.join("-");
}

export function parseRecoveryKey(s: string): Uint8Array {
  const hex = s.replace(/[^0-9a-f]/gi, "");
  if (hex.length !== 64) throw new Error("Recovery key must be 64 hex characters");
  return Uint8Array.from(hex.match(/.{2}/g)!, (h) => parseInt(h, 16));
}

export async function createVault(
  passphrase: string,
  iterations = PBKDF2_ITERATIONS,
): Promise<{ envelope: KeyEnvelope; dek: CryptoKey; dekRaw: Uint8Array; recoveryKey: string }> {
  if (passphrase.length < 10) throw new Error("Passphrase must be at least 10 characters");
  const dekRaw = random(32);
  const recovery = random(32);
  const salt = random(16);
  const envelope: KeyEnvelope = {
    version: 1,
    salt: b64(salt),
    iterations,
    wrappedByPassphrase: await sealBytes(await kekFromPassphrase(passphrase, salt, iterations), dekRaw),
    wrappedByRecovery: await sealBytes(await kekFromRecovery(recovery), dekRaw),
  };
  return { envelope, dek: await importDek(dekRaw), dekRaw, recoveryKey: formatRecoveryKey(recovery) };
}

/** Throws on a wrong passphrase (AES-GCM authentication fails). */
export async function unlockWithPassphrase(env: KeyEnvelope, passphrase: string): Promise<{ dek: CryptoKey; dekRaw: Uint8Array }> {
  const kek = await kekFromPassphrase(passphrase, unb64(env.salt), env.iterations);
  const dekRaw = await openBytes(kek, env.wrappedByPassphrase);
  return { dek: await importDek(dekRaw), dekRaw };
}

export async function unlockWithRecovery(env: KeyEnvelope, recoveryKey: string): Promise<{ dek: CryptoKey; dekRaw: Uint8Array }> {
  const dekRaw = await openBytes(await kekFromRecovery(parseRecoveryKey(recoveryKey)), env.wrappedByRecovery);
  return { dek: await importDek(dekRaw), dekRaw };
}

/** Re-wrap the same data key under a new passphrase (no data re-encryption needed). */
export async function changePassphrase(
  env: KeyEnvelope, dekRaw: Uint8Array, newPassphrase: string,
): Promise<KeyEnvelope> {
  if (newPassphrase.length < 10) throw new Error("Passphrase must be at least 10 characters");
  const salt = random(16);
  return {
    ...env,
    salt: b64(salt),
    wrappedByPassphrase: await sealBytes(await kekFromPassphrase(newPassphrase, salt, env.iterations), dekRaw),
  };
}

export async function sealJson(dek: CryptoKey, value: unknown): Promise<Sealed> {
  return sealBytes(dek, enc.encode(JSON.stringify(value)));
}

export async function openJson<T>(dek: CryptoKey, s: Sealed): Promise<T> {
  return JSON.parse(dec.decode(await openBytes(dek, s))) as T;
}

export { importDek };
