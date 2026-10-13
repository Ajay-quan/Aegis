"""Disk-persistent embedding cache: each (model, text) is embedded once, ever.

Large validation runs embed ~200K texts per model; the cache makes reruns, new suites and
ablations nearly free and guarantees every suite sees identical vectors for identical text.
Stored in SQLite (float32 blobs) under the bench cache directory.
"""
from __future__ import annotations

import array
import hashlib
import sqlite3
import time

from adapters.embeddings.backend import EmbeddingBackend, OpenAICompatibleEmbeddingBackend
from bench.sources import CACHE


class CachedEmbedding(EmbeddingBackend):
    def __init__(self, model: str, dim: int, base_url: str = "http://localhost:11434/v1",
                 api_key: str = "", batch: int = 64) -> None:
        self.model, self._dim, self._batch = model, dim, batch
        self._inner = OpenAICompatibleEmbeddingBackend(base_url, model, api_key, dim, batch_size=batch,
                                                       timeout_s=600)
        CACHE.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(CACHE / "embeddings.sqlite")
        self._db.execute("CREATE TABLE IF NOT EXISTS emb (k BLOB PRIMARY KEY, v BLOB)")
        self._mem: dict[bytes, list[float]] = {}
        self.api_calls = self.hits = 0

    @property
    def dimension(self) -> int:
        return self._dim

    def _key(self, text: str) -> bytes:
        return hashlib.sha1(f"{self.model}\x00{text}".encode()).digest()

    async def prefill(self, texts: list[str], progress: bool = False) -> None:
        keys = {}
        for t in texts:
            keys.setdefault(self._key(t), t)
        todo = [k for k in keys if k not in self._mem]
        found = {}
        for i in range(0, len(todo), 900):
            chunk = todo[i:i + 900]
            q = f"SELECT k, v FROM emb WHERE k IN ({','.join('?' * len(chunk))})"
            for k, v in self._db.execute(q, chunk):
                found[k] = array.array("f", v).tolist()
        self._mem.update(found)
        missing = [k for k in todo if k not in found]
        start, done = time.time(), 0
        for i in range(0, len(missing), self._batch * 8):
            chunk = missing[i:i + self._batch * 8]
            vecs = await self._inner.embed([keys[k] for k in chunk])
            self.api_calls += 1
            rows = [(k, array.array("f", v).tobytes()) for k, v in zip(chunk, vecs)]
            self._db.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?)", rows)
            self._db.commit()
            for k, v in zip(chunk, vecs):
                self._mem[k] = v
            done += len(chunk)
            if progress:
                rate = done / max(time.time() - start, 1e-9)
                print(f"    [{self.model}] embedded {done}/{len(missing)} ({rate:.0f}/s, "
                      f"eta {(len(missing) - done) / max(rate, 1e-9) / 60:.1f} min)", flush=True)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in texts if self._key(t) not in self._mem]
        if missing:
            await self.prefill(missing)
        self.hits += len(texts) - len(missing)
        return [self._mem[self._key(t)] for t in texts]

    def evict(self) -> None:
        """Drop the in-memory layer (keeps the disk cache) to bound RAM between datasets."""
        self._mem.clear()
