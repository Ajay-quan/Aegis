"""Target adapters. A target is anything that can add, search, update and delete memories.

Implement ``Target`` to audit a new system. Unsupported operations raise ``Unsupported`` and the
checks that need them are reported as *skipped*, never as passed.
"""
from __future__ import annotations

import math
import zlib
import uuid
from typing import Any, Literal, Protocol

import httpx

Source = Literal["user", "tool"]


class Unsupported(Exception):
    pass


class Target(Protocol):
    name: str

    async def add(self, user_id: str, text: str, source: Source = "user") -> str: ...
    async def search(self, user_id: str, query: str, k: int = 10) -> list[str]: ...
    async def update(self, user_id: str, memory_id: str, new_text: str) -> None: ...
    async def delete(self, user_id: str, memory_id: str) -> None: ...
    async def delete_user(self, user_id: str) -> None: ...
    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# AegisMem (HTTP)
# ---------------------------------------------------------------------------

class AegisMemTarget:
    name = "aegismem"

    def __init__(self, base_url: str, api_key: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/api/v1", headers=headers,
                                       timeout=30, transport=transport)

    async def _post(self, path: str, body: dict[str, Any], **kw: Any) -> Any:
        r = await self._http.post(path, json=body, **kw)
        r.raise_for_status()
        return r.json()

    async def add(self, user_id: str, text: str, source: Source = "user") -> str:
        st = "tool_output" if source == "tool" else "user_message"
        return (await self._post("/ingest", {"text": text, "user_id": user_id, "source_type": st,
                                             "metadata": {"origin": "audit:" + source}}))["memory_id"]

    async def search(self, user_id: str, query: str, k: int = 10) -> list[str]:
        r = await self._post("/retrieve", {"query": query, "user_id": user_id, "top_k": k})
        return [x["content"] for x in r["results"]]

    async def update(self, user_id: str, memory_id: str, new_text: str) -> None:
        await self._post("/corrections", {"user_id": user_id, "memory_id": memory_id,
                                          "kind": "outdated", "corrected_text": new_text})

    async def delete(self, user_id: str, memory_id: str) -> None:
        await self._post("/forget", {"user_id": user_id, "memory_ids": [memory_id]})

    async def delete_user(self, user_id: str) -> None:
        await self._post("/forget", {"user_id": user_id, "all_for_user": True})

    async def close(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Mem0 (open-source REST server). Field names follow Mem0's documented REST API;
# verify against your server version (`--target mem0`).
# ---------------------------------------------------------------------------

class Mem0Target:
    name = "mem0"

    def __init__(self, base_url: str, api_key: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        headers = {"Authorization": f"Token {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=60,
                                       transport=transport)

    async def add(self, user_id: str, text: str, source: Source = "user") -> str:
        role = "user" if source == "user" else "assistant"
        r = await self._http.post("/memories", json={
            "messages": [{"role": role, "content": text}], "user_id": user_id,
            "metadata": {"source": source}, "infer": False})
        r.raise_for_status()
        data = r.json()
        results = data.get("results", data if isinstance(data, list) else [])
        if not results:
            raise Unsupported("mem0 returned no memory id (inference may have dropped it)")
        return results[0]["id"]

    async def search(self, user_id: str, query: str, k: int = 10) -> list[str]:
        r = await self._http.post("/search", json={"query": query, "user_id": user_id, "limit": k})
        r.raise_for_status()
        data = r.json()
        rows = data.get("results", data if isinstance(data, list) else [])
        return [row.get("memory") or row.get("text", "") for row in rows]

    async def update(self, user_id: str, memory_id: str, new_text: str) -> None:
        r = await self._http.put(f"/memories/{memory_id}", json={"text": new_text})
        r.raise_for_status()

    async def delete(self, user_id: str, memory_id: str) -> None:
        r = await self._http.delete(f"/memories/{memory_id}")
        r.raise_for_status()

    async def delete_user(self, user_id: str) -> None:
        r = await self._http.delete("/memories", params={"user_id": user_id})
        r.raise_for_status()

    async def close(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Mem0 open-source library, in process (`pip install mem0ai`). ``config`` is a Mem0 config
# dict (vector store, embedder, llm). Uses infer=False so the audit measures storage and
# retrieval semantics, not an LLM's extraction choices.
# ---------------------------------------------------------------------------

class Mem0LibraryTarget:
    name = "mem0-oss-library"

    def __init__(self, config: dict[str, Any]) -> None:
        from mem0 import Memory  # lazy: optional dependency
        config = dict(config)
        self._infer = bool(config.pop("infer", False))  # True = Mem0's default LLM extraction
        self.name = f"mem0-oss-library(infer={self._infer})"
        self._mem = Memory.from_config(config)

    async def _run(self, fn: Any, *a: Any, **kw: Any) -> Any:
        import asyncio
        return await asyncio.to_thread(fn, *a, **kw)

    async def add(self, user_id: str, text: str, source: Source = "user") -> str:
        role = "user" if source == "user" else "assistant"
        r = await self._run(self._mem.add, [{"role": role, "content": text}], user_id=user_id,
                            metadata={"source": source}, infer=self._infer)
        results = r.get("results", []) if isinstance(r, dict) else r
        if not results:
            # With infer=True the LLM may decline to store anything: that is a valid outcome,
            # and the checks still judge what search returns afterwards.
            return ""
        return results[0]["id"]

    async def search(self, user_id: str, query: str, k: int = 10) -> list[str]:
        try:
            r = await self._run(self._mem.search, query, top_k=k, filters={"user_id": user_id})
        except TypeError:
            r = await self._run(self._mem.search, query, user_id=user_id, limit=k)
        rows = r.get("results", []) if isinstance(r, dict) else r
        return [row.get("memory", "") for row in rows]

    async def update(self, user_id: str, memory_id: str, new_text: str) -> None:
        if not memory_id:
            raise Unsupported("nothing was stored to update (LLM extraction dropped it)")
        await self._run(self._mem.update, memory_id, text=new_text)

    async def delete(self, user_id: str, memory_id: str) -> None:
        if not memory_id:
            raise Unsupported("nothing was stored to delete (LLM extraction dropped it)")
        await self._run(self._mem.delete, memory_id)

    async def delete_user(self, user_id: str) -> None:
        await self._run(self._mem.delete_all, user_id=user_id)

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Reference: a typical naive vector memory (soft delete, append-only updates, no screening).
# Used to calibrate the audit and as a teaching example of common failure modes.
# ---------------------------------------------------------------------------

def _embed(text: str, dim: int = 64) -> list[float]:
    vec = [0.0] * dim
    words = text.lower().split()
    for w in words:
        vec[zlib.crc32(w.encode()) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


class NaiveVectorTarget:
    name = "naive-vector-store"

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def add(self, user_id: str, text: str, source: Source = "user") -> str:
        mid = str(uuid.uuid4())
        self.rows[mid] = {"user_id": user_id, "text": text, "vec": _embed(text), "deleted": False}
        return mid

    async def search(self, user_id: str, query: str, k: int = 10) -> list[str]:
        q = _embed(query)
        # Common bug: soft-deleted rows stay in the index and are not filtered at query time.
        scored = sorted(self.rows.values(), key=lambda r: -sum(a * b for a, b in zip(q, r["vec"])))
        return [r["text"] for r in scored if r["user_id"] == user_id][:k]

    async def update(self, user_id: str, memory_id: str, new_text: str) -> None:
        await self.add(user_id, new_text)  # append-only: old version still retrievable

    async def delete(self, user_id: str, memory_id: str) -> None:
        self.rows[memory_id]["deleted"] = True  # soft delete only

    async def delete_user(self, user_id: str) -> None:
        for r in self.rows.values():
            if r["user_id"] == user_id:
                r["deleted"] = True

    async def close(self) -> None:
        return None
