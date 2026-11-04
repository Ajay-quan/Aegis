"""Lexical relevance scoring — lightweight token-overlap and keyword signals.

Provides a secondary retrieval signal independent of dense embeddings so the
system is not solely dependent on vector similarity.
"""
from __future__ import annotations

import re
from collections import Counter

# Tokens that carry no informational value for relevance matching.
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out", "off",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "don", "now",
    "and", "but", "or", "if", "what", "which", "who", "whom", "this",
    "that", "these", "those", "i", "me", "my", "myself", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "it", "its", "they",
    "them", "their", "about", "up",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenization with stop-word removal."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP_WORDS]


def compute_token_overlap(query: str, content: str) -> float:
    """Jaccard-like token overlap ratio between query and memory content."""
    q_tokens = set(_tokenize(query))
    c_tokens = set(_tokenize(content))
    if not q_tokens:
        return 0.0
    intersection = q_tokens & c_tokens
    # Weight by how many query tokens appear in content (recall-oriented).
    return len(intersection) / len(q_tokens)


def compute_keyword_boost(query: str, content: str) -> float:
    """Boost score for high-value keyword matches (nouns, proper nouns, numbers)."""
    q_tokens = _tokenize(query)
    c_lower = content.lower()
    if not q_tokens:
        return 0.0
    # Count how many unique query tokens appear as substrings in content.
    hits = sum(1 for t in set(q_tokens) if t in c_lower)
    return hits / len(set(q_tokens))


def compute_exact_phrase_bonus(query: str, content: str) -> float:
    """Bonus if a substantial phrase from the query appears verbatim in content."""
    q_lower = query.lower().strip()
    c_lower = content.lower()

    # Check full query match.
    if q_lower in c_lower:
        return 1.0

    # Check 3-gram and 4-gram phrase windows from the query.
    q_words = q_lower.split()
    if len(q_words) < 3:
        return 1.0 if q_lower in c_lower else 0.0

    best = 0.0
    for window in (4, 3):
        if len(q_words) < window:
            continue
        for i in range(len(q_words) - window + 1):
            phrase = " ".join(q_words[i : i + window])
            if phrase in c_lower:
                best = max(best, window / len(q_words))
    return best


def compute_lexical_score(query: str, content: str) -> float:
    """Combined lexical relevance score in [0, 1].

    Blends token overlap (primary), keyword boost (secondary),
    and exact phrase bonus (tertiary).
    """
    overlap = compute_token_overlap(query, content)
    keyword = compute_keyword_boost(query, content)
    phrase = compute_exact_phrase_bonus(query, content)
    # Weighted blend — overlap is the primary signal.
    return min(1.0, 0.50 * overlap + 0.30 * keyword + 0.20 * phrase)
