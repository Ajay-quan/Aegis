"""Render retrieved memories as a time-aware context block for an agent.

Memories are shown oldest to newest with their dates, so a reader can tell which of two
conflicting statements is current (LongMemEval, Wu et al. 2024: time-aware presentation of
history improves temporal and knowledge-update questions). Facts that the store already knows
were replaced are never served (integrity guard); this handles changes nobody declared.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.schemas.memory import MemoryItem

HEADER = ("Memories about this user, oldest first. Later entries reflect more recent information: "
          "if two entries disagree, the later one is the current state.")


def _when(m: MemoryItem) -> datetime:
    t = m.event_time or m.created_at
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def render_entries(entries: list[tuple[datetime, str]], now: datetime | None = None) -> str:
    """``entries`` are (when, text) pairs in any order."""
    if not entries:
        return ""
    lines = [HEADER]
    if now is not None:
        lines.append(f"Current date: {now:%Y-%m-%d}")
    for when, text in sorted(entries, key=lambda e: e[0]):
        lines.append(f"- [{when:%Y-%m-%d %H:%M}] {text}")
    return "\n".join(lines)


def render_context(memories: list[MemoryItem], now: datetime | None = None) -> str:
    return render_entries([(_when(m), m.content) for m in memories], now)
