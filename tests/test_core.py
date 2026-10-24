import asyncio
from datetime import datetime, timedelta

from app.card import render, topic_title
from app.db import CLOSED, OPEN, PENDING, Store
from app.solo import SoloKey, SoloPayment, SoloProfile


def run(coro):
    return asyncio.run(coro)


def test_store_flow(tmp_path):
    async def go():
        s = Store(str(tmp_path / "t.db"))
        await s.open(ticket_start=50)
        t = await s.create(111, "Ann <b>", "ann_1")
        assert t.id == 51 and t.num == "T000051" and t.status == OPEN
        await s.update(t.id, topic_id=7, status=PENDING, last_agent_at=1)
        assert (await s.by_topic(7)).id == 51
        assert (await s.active_for_user(111)).id == 51
        assert [x.id for x in await s.stale_pending(10)] == [51]
        await s.add_message(51, "in", 111, 1000, 2000, "hi")
        assert await s.user_msg_for_topic_msg(51, 2000) == 1000
        assert await s.topic_msg_for_user_msg(51, 1000) == 2000
        await s.update(t.id, status=CLOSED, closed_at=5)
        assert await s.active_for_user(111) is None
        assert (await s.last_closed_for_user(111)).id == 51
        # SQL-инъекция в данных просто сохраняется как строка
        await s.ban(111, "'); DROP TABLE tickets; --", 1)
        assert await s.is_banned(111)
        assert (await s.get(51)) is not None
        # повторный open не сбрасывает нумерацию
        await s.close()
        s2 = Store(str(tmp_path / "t.db"))
        await s2.open(ticket_start=50)
        assert (await s2.create(222, "B", None)).id == 52
        await s2.close()

    run(go())


def test_card_escapes_and_underscores(tmp_path):
    async def go():
        s = Store(str(tmp_path / "c.db"))
        await s.open()
        t = await s.create(5, "<script>_x_", "user_name_")
        await s.close()
        return t

    t = run(go())
    p = SoloProfile(
        found=True, balance=10, registered=datetime(2026, 1, 1), email="shadow_deputy@proton.me",
        keys=[SoloKey("69hzvt1w", datetime.now() + timedelta(days=5), False, "cluster1",
                      "https://example.com/sub/AbC_123", "200 ГБ", 3, 200, 12.4)],
        payments=[SoloPayment(300, "kassai", "success", datetime(2026, 10, 1))], paid_total=300,
    )
    html = render(t, p)
    assert "&lt;script&gt;_x_" in html
    assert "shadow_deputy@proton.me" in html
    assert "12/200 ГБ" in html
    assert "<script>" not in html
    assert render(t, None).count("недоступны") == 1
    assert "Нет в базе" in render(t, SoloProfile(found=False))
    assert topic_title(t).startswith("🔴 #T000001")
