"""Embedding backends for AegisMem - swappable by configuration."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

import numpy as np

from core.exceptions import EmbeddingError

logger = logging.getLogger(__name__)


class EmbeddingBackend(ABC):
    """Base class for embedding backends."""

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0]

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        va, vb = np.array(a), np.array(b)
        norm_a, norm_b = np.linalg.norm(va), np.linalg.norm(vb)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))


class SentenceTransformerBackend(EmbeddingBackend):
    """Local sentence-transformers embedding backend."""

    def __init__(self, model_name: str = "BAAI/bge-large-en-v1.5", device: str = "cpu") -> None:
        self._model_name = model_name
        self._device = device
        self._model: Any = None
        self._dim: int = 0

    def _load(self) -> None:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {self._model_name}")
                self._model = SentenceTransformer(self._model_name, device=self._device)
                self._dim = self._model.get_sentence_embedding_dimension() or 1024
                logger.info(f"Embedding model loaded, dim={self._dim}")
            except Exception as e:
                raise EmbeddingError(f"Failed to load sentence-transformer: {e}") from e

    @property
    def dimension(self) -> int:
        if not self._dim:
            self._load()
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: self._model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).tolist(),
            )
            return embeddings
        except Exception as e:
            raise EmbeddingError(f"Embedding failed: {e}") from e


class MockEmbeddingBackend(EmbeddingBackend):
    """Deterministic mock embedding for tests."""

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib, random
        results = []
        for text in texts:
            seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
            rng = random.Random(seed)
            vec = [rng.gauss(0, 1) for _ in range(self._dim)]
            norm = sum(x**2 for x in vec) ** 0.5 or 1.0
            results.append([x / norm for x in vec])
        return results


class _ContextTooLong(Exception):
    pass


class OpenAICompatibleEmbeddingBackend(EmbeddingBackend):
    """Any OpenAI-compatible ``POST {base}/embeddings`` API (OpenAI, Voyage, vLLM, Ollama /v1, ...).

    Batches requests, retries transient failures, and verifies the returned dimension so a
    model/index mismatch fails loudly instead of corrupting the vector index.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "", dimension: int = 0,
                 batch_size: int = 64, timeout_s: float = 30.0, max_retries: int = 3,
                 max_input_chars: int = 0) -> None:
        import httpx
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s)
        self._model = model
        self._dim = dimension
        self._batch = batch_size
        self._retries = max_retries
        # 0 = unknown: learned from the provider's first "context length" rejection.
        self._max_chars = max_input_chars

    @property
    def dimension(self) -> int:
        return self._dim

    def _clip(self, inputs: list[str]) -> list[str]:
        return [t[: self._max_chars] for t in inputs] if self._max_chars else inputs

    async def _post(self, inputs: list[str]) -> list[list[float]]:
        """Embed a batch. Inputs longer than the model's context are truncated (the full text is
        still stored; only its embedding uses the leading part). The limit is learned adaptively
        from the provider's rejection, so long memories never become unindexable."""
        import asyncio
        import httpx
        for _ in range(8):
            try:
                return await self._post_once(self._clip(inputs))
            except _ContextTooLong:
                longest = max(len(t) for t in self._clip(inputs))
                self._max_chars = max(256, int(longest * 0.7))
                logger.warning(f"embedding input exceeded {self._model} context; truncating to "
                               f"{self._max_chars} chars")
        raise EmbeddingError(f"could not fit inputs into {self._model} context")

    async def _post_once(self, inputs: list[str]) -> list[list[float]]:
        import asyncio
        import httpx
        for attempt in range(self._retries + 1):
            try:
                r = await self._http.post("/embeddings", json={"model": self._model, "input": inputs})
                if r.status_code == 400 and "context length" in r.text.lower():
                    raise _ContextTooLong()
                if r.status_code in (429, 500, 502, 503, 504) and attempt < self._retries:
                    await asyncio.sleep(min(8.0, 0.5 * 2 ** attempt))
                    continue
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
            except (httpx.TransportError,) as e:
                if attempt >= self._retries:
                    raise EmbeddingError(f"embedding API unreachable: {e}") from e
                await asyncio.sleep(min(8.0, 0.5 * 2 ** attempt))
        raise EmbeddingError("embedding API retries exhausted")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            out.extend(await self._post(texts[i:i + self._batch]))
        for v in out:
            if self._dim and len(v) != self._dim:
                raise EmbeddingError(
                    f"model {self._model} returned {len(v)} dims; EMBEDDING_DIMENSION is {self._dim}")
        return out


# Known output sizes, so a bare get_embedding_backend("openai") is correctly dimensioned.
KNOWN_DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072,
                    "text-embedding-ada-002": 1536, "nomic-embed-text": 768}

OpenAIEmbeddingBackend = OpenAICompatibleEmbeddingBackend  # pre-merge name


@lru_cache(maxsize=8)
def get_embedding_backend(backend: str = "mock", model_name: str = "", dimension: int | None = None,
                          api_base: str = "", api_key: str = "") -> EmbeddingBackend:
    """Factory for embedding backends (cached per configuration)."""
    if backend == "openai":
        model = model_name or "text-embedding-3-small"
        dim = dimension or KNOWN_DIMENSIONS.get(model, 0)
        return OpenAICompatibleEmbeddingBackend(api_base or "https://api.openai.com/v1", model, api_key, dim)
    if backend == "sentence_transformers":
        return SentenceTransformerBackend(model_name=model_name or "BAAI/bge-large-en-v1.5")
    if backend == "mock":
        return MockEmbeddingBackend(dim=dimension or 384)
    raise EmbeddingError(f"Unknown embedding backend: {backend}")
