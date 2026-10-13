from datetime import datetime, timezone

from core.schemas.memory import MemoryItem
from domain.memory.context import HEADER, render_context


def _m(text: str, day: int) -> MemoryItem:
    return MemoryItem(namespace="user:u", user_id="u", content=text,
                      event_time=datetime(2023, 5, day, tzinfo=timezone.utc))


def test_context_is_chronological_with_dates():
    out = render_context([_m("sneakers now in a shoe rack", 29), _m("sneakers under my bed", 25)],
                         now=datetime(2023, 6, 23, tzinfo=timezone.utc))
    lines = out.splitlines()
    assert lines[0] == HEADER and lines[1] == "Current date: 2023-06-23"
    assert lines[2] == "- [2023-05-25 00:00] sneakers under my bed"
    assert lines[3] == "- [2023-05-29 00:00] sneakers now in a shoe rack"


def test_empty():
    assert render_context([]) == ""
