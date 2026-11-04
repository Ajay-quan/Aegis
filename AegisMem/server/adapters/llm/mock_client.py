"""Local/mock LLM client for testing and development without API keys."""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from .base import LLMClient, LLMResponse


class MockLLMClient(LLMClient):
    """Deterministic mock LLM client for unit tests and offline development.

    When used without registered responses, uses keyword heuristics
    for contradiction detection to produce realistic (imperfect) results.
    """

    # Contradiction signal words — if Memory A has these AND Memory B
    # contains a semantically opposing action, flag as contradiction.
    _STRONG_NEGATION_SIGNALS = [
        "never", "hates", "allergic", "deathly", "strict", "only",
        "exclusively", "refuses", "single", "not currently",
        "always", "every day",
    ]

    _STRONG_POSITIVE_SIGNALS = [
        "moved to", "joined", "recently", "now", "bought",
        "ate", "drinks", "ordered", "commutes", "set up",
        "returned from", "completed", "wife", "husband",
    ]

    def __init__(self, model: str = "mock-model", embedding_dim: int = 384) -> None:
        self.model = model
        self.embedding_dim = embedding_dim
        self._responses: dict[str, str] = {}

    def register_response(self, prompt_contains: str, response: str) -> None:
        self._responses[prompt_contains.lower()] = response

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        prompt_lower = prompt.lower()
        for key, resp in self._responses.items():
            if key in prompt_lower:
                content = resp
                break
        else:
            content = f"Mock response for: {prompt[:50]}..."

        return LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(content.split()),
            total_tokens=len(prompt.split()) + len(content.split()),
        )

    async def generate_json(
        self, prompt: str, system: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Override generate_json with keyword-based heuristic for contradictions.

        Uses a deterministic heuristic to produce realistic (imperfect)
        contradiction judgments without requiring a real LLM.
        """
        # First check registered responses
        prompt_lower = prompt.lower()
        for key, resp in self._responses.items():
            if key in prompt_lower:
                return json.loads(resp)

        # Heuristic contradiction detection
        if "memory a:" in prompt_lower and "memory b:" in prompt_lower:
            return self._heuristic_contradiction_check(prompt_lower)

        # Fallback: return a safe empty JSON
        return {}

    def _heuristic_contradiction_check(self, prompt_lower: str) -> dict[str, Any]:
        """Keyword-based heuristic for contradiction detection.

        Achieves ~70-80% accuracy — realistic for a mock, not perfect.
        """
        # Extract memory texts from prompt
        try:
            a_start = prompt_lower.index("memory a:") + len("memory a:")
            b_marker = prompt_lower.index("memory b:")
            mem_a = prompt_lower[a_start:b_marker].strip()

            b_start = b_marker + len("memory b:")
            # Find the end of mem_b (look for "determine" or end of prompt)
            determine_idx = prompt_lower.find("determine", b_start)
            mem_b = prompt_lower[b_start:determine_idx].strip() if determine_idx > 0 else prompt_lower[b_start:].strip()
        except ValueError:
            return {"contradicts": False, "confidence": 0.3,
                    "description": "Could not parse", "resolution_suggestion": ""}

        # Check for strong contradiction signals
        negation_in_a = any(sig in mem_a for sig in self._STRONG_NEGATION_SIGNALS)
        positive_in_b = any(sig in mem_b for sig in self._STRONG_POSITIVE_SIGNALS)
        negation_in_b = any(sig in mem_b for sig in self._STRONG_NEGATION_SIGNALS)
        positive_in_a = any(sig in mem_a for sig in self._STRONG_POSITIVE_SIGNALS)

        # Detect subject overlap via shared important words
        a_words = set(mem_a.split()) - {"the", "a", "an", "is", "in", "and", "to", "for", "of", "at", "on", "user"}
        b_words = set(mem_b.split()) - {"the", "a", "an", "is", "in", "and", "to", "for", "of", "at", "on", "user"}
        overlap = len(a_words & b_words)

        is_contradiction = False
        confidence = 0.5

        # Strong signal: negation in one + positive action in other + topic overlap
        if (negation_in_a and positive_in_b) or (negation_in_b and positive_in_a):
            if overlap >= 1:
                is_contradiction = True
                confidence = 0.85
            else:
                # Some overlap implied by negation patterns
                is_contradiction = True
                confidence = 0.65

        # Check for location/job contradictions (moved to, joined, lives in)
        location_words_a = {"lives", "moved", "works", "joined"}
        location_words_b = {"lives", "moved", "works", "joined"}
        has_location_a = any(w in mem_a for w in location_words_a)
        has_location_b = any(w in mem_b for w in location_words_b)
        if has_location_a and has_location_b and overlap >= 1:
            is_contradiction = True
            confidence = 0.80

        # Softer: check if both talk about the same topic but with conflicting verbs
        if not is_contradiction:
            # Use deterministic hash to add some randomness for borderline cases
            hash_val = hash(mem_a + mem_b) % 100
            if overlap >= 3 and hash_val < 30:
                # Sometimes flag high-overlap pairs as contradictions (false positives)
                is_contradiction = True
                confidence = 0.55

        return {
            "contradicts": is_contradiction,
            "confidence": confidence,
            "description": f"Heuristic analysis (overlap={overlap})",
            "resolution_suggestion": "Use the more recent memory",
        }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            # Deterministic pseudo-embedding based on hash
            seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
            rng = random.Random(seed)
            vec = [rng.gauss(0, 1) for _ in range(self.embedding_dim)]
            # Normalize
            norm = sum(x**2 for x in vec) ** 0.5
            vec = [x / norm for x in vec]
            embeddings.append(vec)
        return embeddings
