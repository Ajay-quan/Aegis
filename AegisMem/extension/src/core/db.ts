/** IndexedDB for Recall: key record + one sealed record per conversation. Plaintext never touches disk. */
import type { Sealed } from "./crypto";
import type { KeyRecord } from "./keys";

const NAME = "aegismem-recall";
const VERSION = 1;

export interface SealedConversation {
  id: string;
  sealed: Sealed;
}

let dbp: Promise<IDBDatabase> | null = null;
function open(): Promise<IDBDatabase> {
  dbp ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta");
      if (!db.objectStoreNames.contains("convs")) db.createObjectStore("convs", { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => {
      dbp = null;
      reject(req.error);
    };
  });
  return dbp;
}

async function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T> {
  const db = await open();
  return new Promise<T>((resolve, reject) => {
    const t = db.transaction(store, mode);
    const req = fn(t.objectStore(store));
    t.oncomplete = () => resolve(req ? (req.result as T) : (undefined as T));
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

export const db = {
  getKey: () => tx<KeyRecord | undefined>("meta", "readonly", (s) => s.get("key")),
  putKey: (k: KeyRecord) => tx("meta", "readwrite", (s) => s.put(k, "key")),
  all: () => tx<SealedConversation[]>("convs", "readonly", (s) => s.getAll()),
  get: (id: string) => tx<SealedConversation | undefined>("convs", "readonly", (s) => s.get(id)),
  put: (r: SealedConversation) => tx("convs", "readwrite", (s) => s.put(r)),
  putMany: async (rs: SealedConversation[]) => {
    const d = await open();
    await new Promise<void>((resolve, reject) => {
      const t = d.transaction("convs", "readwrite");
      const s = t.objectStore("convs");
      for (const r of rs) s.put(r);
      t.oncomplete = () => resolve();
      t.onerror = () => reject(t.error);
    });
  },
  delete: (id: string) => tx("convs", "readwrite", (s) => s.delete(id)),
  count: () => tx<number>("convs", "readonly", (s) => s.count()),
  clearConvs: () => tx("convs", "readwrite", (s) => s.clear()),
  wipe: async () => {
    await tx("convs", "readwrite", (s) => s.clear());
    await tx("meta", "readwrite", (s) => s.clear());
  },
};
