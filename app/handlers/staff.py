import logging
import time
from html import escape

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..card import STATUS_ICON
from ..db import Store, Ticket
from ..service import Service

log = logging.getLogger(__name__)
router = Router(name="staff")

COPYABLE = {
    ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT, ContentType.AUDIO,
    ContentType.VOICE, ContentType.VIDEO_NOTE, ContentType.ANIMATION, ContentType.STICKER,
    ContentType.LOCATION, ContentType.CONTACT,
}


def setup(forum_chat_id: int) -> Router:
    router.message.filter(F.chat.id == forum_chat_id)
    router.callback_query.filter(F.message.chat.id == forum_chat_id)
    return router


async def _ticket(m: Message, store: Store) -> Ticket | None:
    if not m.message_thread_id or not m.is_topic_message:
        return None
    return await store.by_topic(m.message_thread_id)


# --- служебные события тем: закрытие/открытие из интерфейса Telegram ---

@router.message(F.forum_topic_closed)
async def topic_closed(m: Message, store: Store, service: Service) -> None:
    t = await _ticket(m, store)
    if t:
        await service.close(t, m.from_user.full_name if m.from_user else None)


@router.message(F.forum_topic_reopened)
async def topic_reopened(m: Message, store: Store, service: Service) -> None:
    t = await _ticket(m, store)
    if t:
        await service.reopen(t, m.from_user.full_name if m.from_user else "—")


# --- команды в общей теме ---

@router.message(Command("help"))
async def help_(m: Message) -> None:
    await m.reply(texts.STAFF_HELP)


@router.message(Command("open"))
async def open_list(m: Message, store: Store) -> None:
    items = await store.list_active()
    if not items:
        await m.reply("Открытых тикетов нет 🎉")
        return
    chat = str(m.chat.id).removeprefix("-100")
    lines = [f"<b>Активные тикеты: {len(items)}</b>"]
    for t in items:
        age = int((time.time() - (t.last_client_at or t.created_at)) / 3600)
        who = escape(t.user_name or str(t.user_id))
        lead = f" · {escape(t.assignee_name)}" if t.assignee_name else ""
        lines.append(f'{STATUS_ICON[t.status]} <a href="https://t.me/c/{chat}/{t.topic_id}">#{t.num}</a> {who} · {age} ч{lead}')
    await m.reply("\n".join(lines)[:4000], disable_web_page_preview=True)


@router.message(Command("stats"))
async def stats(m: Message, store: Store) -> None:
    week = int(time.time()) - 7 * 86400
    s = await store.stats(week)
    avg = f"{s['avg_rating']:.1f} ({s['rated']})" if s["avg_rating"] else "—"
    await m.reply(
        f"🔴 ждут ответа: {s['open']}\n🟡 ждём клиента: {s['pending']}\n"
        f"За 7 дней: создано {s['created']}, закрыто {s['closed']}\n⭐ средняя оценка: {avg}"
    )


# --- команды внутри темы тикета ---

@router.message(Command("close", "reopen", "take", "card", "note", "ban", "unban"))
async def ticket_cmd(m: Message, command: CommandObject, store: Store, service: Service) -> None:
    t = await _ticket(m, store)
    if not t:
        await m.reply("Команду нужно отправить внутри темы тикета.")
        return
    name = m.from_user.full_name
    cmd, arg = command.command, (command.args or "").strip()
    if cmd == "close":
        await service.close(t, name)
    elif cmd == "reopen":
        await service.reopen(t, name)
    elif cmd == "take":
        await service.take(t, m.from_user.id, name)
        await m.reply(f"🙋 Тикет ведёт {escape(name)}")
    elif cmd == "card":
        await service.resend_card(t)
        await service.refresh(t)
        try:
            await m.delete()
        except Exception:
            pass
    elif cmd == "note":
        await store.add_message(t.id, "note", m.from_user.id, None, m.message_id, arg)
        await m.reply("📝 Заметка сохранена (клиент не видит)")
    elif cmd == "ban":
        await store.ban(t.user_id, arg or None, m.from_user.id)
        await service.close(t, name)
        await m.reply(f"⛔️ Клиент заблокирован в поддержке{': ' + escape(arg) if arg else ''}")
    elif cmd == "unban":
        await store.unban(t.user_id)
        await m.reply("Клиент разблокирован")


@router.message(F.message_thread_id, F.is_topic_message)
async def agent_message(m: Message, store: Store, service: Service) -> None:
    if m.from_user is None or m.from_user.is_bot or m.content_type not in COPYABLE:
        return  # служебные сообщения (переименование темы, закреп и т.п.) клиенту не шлём
    t = await _ticket(m, store)
    if not t:
        return
    if (m.text or "").startswith("!"):
        await store.add_message(t.id, "note", m.from_user.id, None, m.message_id, m.text[1:].strip())
        return
    if m.text and m.text.startswith("/"):
        return  # неизвестная команда — не отправляем клиенту
    await service.to_client(m, t)


# --- кнопки карточки ---

@router.callback_query(F.data.startswith("t:"))
async def card_button(c: CallbackQuery, store: Store, service: Service) -> None:
    _, action, tid = c.data.split(":")
    t = await store.get(int(tid))
    if not t:
        await c.answer("Тикет не найден", show_alert=True)
        return
    name = c.from_user.full_name
    if action == "close":
        await service.close(t, name)
        await c.answer("Закрыт")
    elif action == "reopen":
        await service.reopen(t, name)
        await c.answer("Открыт")
    elif action == "take":
        await service.take(t, c.from_user.id, name)
        await c.answer("Тикет ваш")
    elif action == "card":
        await service.refresh(t)
        await c.answer("Обновлено")
    else:
        await c.answer()
