/** IndexedDB persistence. Holds only the key envelope and sealed (encrypted) records. */
import type { KeyEnvelope, Sealed } from "./crypto";

const DB = "aegismem";
const VERSION = 1;

export interface SealedRecord {
  id: string;
  sealed: Sealed;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta");
      if (!db.objectStoreNames.contains("memories")) db.createObjectStore("memories", { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function run<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(store, mode);
        const req = fn(tx.objectStore(store));
        tx.oncomplete = () => {
          db.close();
          resolve(req ? (req.result as T) : (undefined as T));
        };
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
      }),
  );
}

export const store = {
  getEnvelope: () => run<KeyEnvelope | undefined>("meta", "readonly", (s) => s.get("envelope")),
  putEnvelope: (e: KeyEnvelope) => run("meta", "readwrite", (s) => s.put(e, "envelope")),
  all: () => run<SealedRecord[]>("memories", "readonly", (s) => s.getAll()),
  put: (r: SealedRecord) => run("memories", "readwrite", (s) => s.put(r)),
  delete: (id: string) => run("memories", "readwrite", (s) => s.delete(id)),
  has: (id: string) => run<number>("memories", "readonly", (s) => s.count(id)).then((n) => n > 0),
  clear: () => run("memories", "readwrite", (s) => s.clear()),
  wipeAll: async () => {
    await run("memories", "readwrite", (s) => s.clear());
    await run("meta", "readwrite", (s) => s.clear());
  },
};
