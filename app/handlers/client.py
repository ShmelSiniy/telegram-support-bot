import logging
import time
from collections import defaultdict, deque

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..config import Settings
from ..db import Store
from ..service import Service

log = logging.getLogger(__name__)
router = Router(name="client")
router.message.filter(F.chat.type == "private")

_hits: dict[int, deque] = defaultdict(deque)
_warned: dict[int, float] = {}


def _flooding(user_id: int, cfg: Settings) -> bool:
    q, t = _hits[user_id], time.monotonic()
    q.append(t)
    while q and t - q[0] > cfg.spam_window:
        q.popleft()
    return len(q) > cfg.spam_limit


@router.message(CommandStart())
async def start(m: Message, store: Store) -> None:
    if await store.is_banned(m.from_user.id):
        return
    await m.answer(texts.START)


@router.message()
async def incoming(m: Message, store: Store, service: Service, settings: Settings) -> None:
    uid = m.from_user.id
    if await store.is_banned(uid):
        return
    if _flooding(uid, settings):
        if time.monotonic() - _warned.get(uid, 0) > settings.spam_window:
            _warned[uid] = time.monotonic()
            await m.answer(texts.SPAM)
        return
    await service.from_client(m)


@router.callback_query(F.data.startswith("rate:"))
async def rate(c: CallbackQuery, store: Store, service: Service) -> None:
    _, tid, score = c.data.split(":")
    t = await store.get(int(tid))
    if not t or t.user_id != c.from_user.id:
        await c.answer()
        return
    if t.rating is None:
        await store.update(t.id, rating=int(score))
        await service.refresh(await store.get(t.id))
        await service._note(t, f"⭐ Оценка клиента: {score}/5")
    await c.message.edit_text(texts.RATE_THANKS)
    await c.answer()
