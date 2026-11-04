/**
 * Key management. Every conversation record is sealed with one AES-256-GCM data key.
 *   device mode (default)   the data key is a non-extractable CryptoKey stored in IndexedDB: encrypted
 *                           at rest, no passphrase to remember, unlocked automatically on this device.
 *   passphrase mode         the data key is wrapped by a PBKDF2-600k passphrase key and a recovery key
 *                           (see crypto.ts); it exists in memory only after the user unlocks.
 * Neither mode ever sends a key anywhere. Device mode protects against reading the browser profile's
 * files directly. Passphrase mode also protects against someone using this browser profile.
 */
import { createVault, unlockWithPassphrase, unlockWithRecovery, changePassphrase, importDek, type KeyEnvelope } from "./crypto";

export type KeyMode = "device" | "passphrase";
export type KeyRecord = { mode: "device"; key: CryptoKey } | { mode: "passphrase"; envelope: KeyEnvelope };

export async function newDeviceKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

export async function newPassphraseKey(passphrase: string, iterations?: number) {
  return createVault(passphrase, iterations); // { envelope, dek, dekRaw, recoveryKey }
}

export { unlockWithPassphrase, unlockWithRecovery, changePassphrase, importDek };
