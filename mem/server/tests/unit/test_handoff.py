"""Tests for handoff packet construction."""
from datetime import datetime, timedelta, timezone

from core.schemas.memory import MemoryItem, MemoryLayer, MemoryStatus
from services.handoff_service import HandoffService
from tests.fixtures.conftest import MockPostgresStore

NS = "user:h:agent:chat"


def _mem(content, **kw):
    return MemoryItem(namespace=NS, user_id="h", content=content, **kw)


async def _seed(db):
    old = _mem("User lives in Seattle", memory_type="fact", memory_layer=MemoryLayer.SEMANTIC,
               status=MemoryStatus.SUPERSEDED)
    new = _mem("User lives in Austin", memory_type="fact", memory_layer=MemoryLayer.SEMANTIC,
               parent_memory_ids=[old.memory_id], version=2, importance_score=0.9)
    a = _mem("User is vegetarian", memory_type="fact", memory_layer=MemoryLayer.SEMANTIC,
             contradiction_status="confirmed")
    b = _mem("User ordered a steak", contradiction_status="confirmed")
    a.contradicted_by, b.contradicted_by = [b.memory_id], [a.memory_id]
    pref = _mem("User prefers concise answers", memory_type="fact",
                memory_layer=MemoryLayer.SEMANTIC, importance_score=0.8)
    ep = _mem("Asked about flight options to Denver")
    for m in (old, new, a, b, pref, ep):
        await db.save_memory(m)
    return old, new, a, b, pref, ep


class TestHandoff:
    async def test_sections_and_citations(self):
        db = MockPostgresStore()
        old, new, a, b, pref, ep = await _seed(db)
        p = await HandoffService(db).build(user_id="h")

        oq = p.sections["open_questions"]
        assert len(oq) == 1  # the pair is reported once
        assert oq[0].conflicts_with

        rc = p.sections["recent_changes"][0]
        assert rc.memory_id == new.memory_id and rc.previous == "User lives in Seattle"

        assert pref.memory_id in {i.memory_id for i in p.sections["profile"]}
        assert "Seattle" in p.markdown and new.memory_id[:8] in p.markdown

    async def test_no_item_appears_twice(self):
        db = MockPostgresStore()
        await _seed(db)
        p = await HandoffService(db).build(user_id="h")
        ids = [i.memory_id for items in p.sections.values() for i in items]
        assert len(ids) == len(set(ids))

    async def test_budget_is_respected_and_omissions_reported(self):
        db = MockPostgresStore()
        await _seed(db)
        for i in range(40):
            await db.save_memory(_mem(f"Episode {i}: " + "detail " * 20))
        p = await HandoffService(db).build(user_id="h", token_budget=200)
        assert p.tokens_used <= 200
        assert p.omitted

    async def test_since_filters_activity(self):
        db = MockPostgresStore()
        await _seed(db)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        p = await HandoffService(db).build(user_id="h", since=future)
        assert "recent_activity" not in p.sections
        assert "recent_changes" not in p.sections
