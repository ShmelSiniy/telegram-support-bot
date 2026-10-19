"""Вся логика тикетов: темы форума, пересылка в обе стороны, статусы. Ошибки доставки не глотаются."""

import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyParameters

from . import card, texts
from .config import Settings
from .db import CLOSED, OPEN, PENDING, Store, Ticket, now
from .solo import Solo

log = logging.getLogger(__name__)

TOPIC_GONE = ("thread not found", "topic_deleted", "topic_id_invalid", "message thread not found")


def _topic_gone(e: Exception) -> bool:
    s = str(e).lower()
    return any(m in s for m in TOPIC_GONE)


def _ignorable(e: Exception) -> bool:
    s = str(e).lower()
    return "not modified" in s or "topic_not_modified" in s


def message_text(m: Message) -> str:
    """Короткое текстовое представление сообщения для истории."""
    if m.text:
        return m.text
    kind = next(
        (k for k in ("photo", "video", "document", "voice", "audio", "sticker", "video_note", "animation")
         if getattr(m, k, None)),
        "сообщение",
    )
    cap = f" {m.caption}" if m.caption else ""
    return f"[{kind}]{cap}"


class Service:
    def __init__(self, bot: Bot, store: Store, solo: Solo, cfg: Settings) -> None:
        self.bot = bot
        self.store = store
        self.solo = solo
        self.cfg = cfg
        self.chat = cfg.forum_chat_id

    # --- темы и карточка ---

    async def _create_topic(self, t: Ticket, with_history: bool = False) -> Ticket:
        topic = await self.bot.create_forum_topic(self.chat, card.topic_title(t))
        profile = await self.solo.profile(t.user_id)
        msg = await self.bot.send_message(
            self.chat, card.render(t, profile), message_thread_id=topic.message_thread_id,
            reply_markup=card.keyboard(t), disable_web_page_preview=True,
        )
        try:
            await self.bot.pin_chat_message(self.chat, msg.message_id, disable_notification=True)
        except TelegramBadRequest as e:
            log.warning("pin card #%s: %s", t.num, e)
        await self.store.update(t.id, topic_id=topic.message_thread_id, card_msg_id=msg.message_id)
        t = await self.store.get(t.id)
        if with_history:
            hist = await self.store.recent_messages(t.id)
            if hist:
                lines = ["<i>Тема была удалена, создана заново. Последние сообщения:</i>"]
                for r in hist:
                    who = "👤" if r["direction"] == "in" else "🧑‍💻"
                    lines.append(f"{who} {escape((r['text'] or '')[:300])}")
                await self.bot.send_message(self.chat, "\n".join(lines)[:4000], message_thread_id=t.topic_id)
        return t

    async def refresh(self, t: Ticket) -> None:
        """Перерисовать название темы и карточку под текущий статус."""
        if not t.topic_id:
            return
        try:
            await self.bot.edit_forum_topic(self.chat, t.topic_id, name=card.topic_title(t))
        except TelegramBadRequest as e:
            if not _ignorable(e):
                log.warning("rename topic #%s: %s", t.num, e)
        if t.card_msg_id:
            profile = await self.solo.profile(t.user_id)
            try:
                await self.bot.edit_message_text(
                    card.render(t, profile), chat_id=self.chat, message_id=t.card_msg_id,
                    reply_markup=card.keyboard(t), disable_web_page_preview=True,
                )
            except TelegramBadRequest as e:
                if not _ignorable(e):
                    log.warning("card #%s: %s", t.num, e)

    async def _topic_state(self, t: Ticket, closed: bool) -> bool:
        """Закрыть/открыть тему. False — темы уже нет (удалена)."""
        if not t.topic_id:
            return False
        try:
            if closed:
                await self.bot.close_forum_topic(self.chat, t.topic_id)
            else:
                await self.bot.reopen_forum_topic(self.chat, t.topic_id)
        except TelegramBadRequest as e:
            if _topic_gone(e):
                return False
            if not _ignorable(e) and "topic_closed" not in str(e).lower():
                log.info("topic state #%s: %s", t.num, e)
        return True

    async def _topic_alive(self, t: Ticket) -> bool:
        """Тема существует? Telegram при записи в удалённую тему молча шлёт в General, поэтому проверяем явно."""
        if not t.topic_id:
            return False
        try:
            await self.bot.edit_forum_topic(self.chat, t.topic_id, name=card.topic_title(t))
        except TelegramBadRequest as e:
            if _topic_gone(e):
                return False
            if not _ignorable(e):
                log.warning("probe topic #%s: %s", t.num, e)
        return True

    async def resend_card(self, t: Ticket) -> None:
        """Отправить карточку новым сообщением в конец темы, закрепить, старую убрать."""
        profile = await self.solo.profile(t.user_id)
        msg = await self.bot.send_message(
            self.chat, card.render(t, profile), message_thread_id=t.topic_id,
            reply_markup=card.keyboard(t), disable_web_page_preview=True,
        )
        try:
            await self.bot.pin_chat_message(self.chat, msg.message_id, disable_notification=True)
        except TelegramBadRequest as e:
            log.warning("pin card #%s: %s", t.num, e)
        old = t.card_msg_id
        await self.store.update(t.id, card_msg_id=msg.message_id)
        if old:
            try:
                await self.bot.delete_message(self.chat, old)
            except TelegramBadRequest as e:
                log.info("delete old card #%s: %s", t.num, e)

    # --- клиент → операторы ---

    async def ticket_for_client(self, m: Message) -> tuple[Ticket, bool]:
        """Активный тикет клиента, переоткрытый недавний или новый. Второе значение — создан ли новый."""
        u = m.from_user
        name = u.full_name or ""
        t = await self.store.active_for_user(u.id)
        if t:
            if not await self._topic_alive(t):
                t = await self._create_topic(t, with_history=True)
            return t, False
        last = await self.store.last_closed_for_user(u.id)
        if last and last.auto_closed and last.closed_at and now() - last.closed_at < self.cfg.reopen_hours * 3600:
            await self.store.update(last.id, status=OPEN, closed_at=None, auto_closed=0, user_name=name, username=u.username)
            t = await self.store.get(last.id)
            if await self._topic_state(t, closed=False):
                await self.refresh(t)
                await self._note(t, "↩️ Клиент написал снова — тикет переоткрыт")
            else:  # тему удалили — сразу создаём новую
                t = await self._create_topic(t, with_history=True)
                await self._note(t, "↩️ Клиент написал снова — тикет переоткрыт")
            return t, False
        t = await self.store.create(u.id, name, u.username)
        return await self._create_topic(t), True

    async def from_client(self, m: Message) -> Ticket:
        t, created = await self.ticket_for_client(m)
        sent = await self._copy_to_topic(m, t)
        if sent is None:  # тема пропала — пересоздаём и повторяем
            t = await self._create_topic(t, with_history=True)
            sent = await self._copy_to_topic(m, t)
        await self.store.add_message(t.id, "in", m.from_user.id, m.message_id,
                                     sent.message_id if sent else None, message_text(m))
        if t.status != OPEN:
            await self.store.update(t.id, status=OPEN, last_client_at=now())
            t = await self.store.get(t.id)
            await self.refresh(t)
        else:
            await self.store.update(t.id, last_client_at=now())
        if created:
            await m.answer(texts.CONFIRM.format(num=t.num))
        return t

    async def _copy_to_topic(self, m: Message, t: Ticket):
        reply = None
        if m.reply_to_message:
            target = await self.store.topic_msg_for_user_msg(t.id, m.reply_to_message.message_id)
            if target:
                reply = ReplyParameters(message_id=target, allow_sending_without_reply=True)
        try:
            return await self.bot.copy_message(
                self.chat, m.chat.id, m.message_id, message_thread_id=t.topic_id, reply_parameters=reply
            )
        except TelegramBadRequest as e:
            if _topic_gone(e):
                log.warning("тема #%s удалена: %s", t.num, e)
                return None
            raise

    # --- оператор → клиент ---

    async def to_client(self, m: Message, t: Ticket) -> None:
        reply = None
        if m.reply_to_message:
            target = await self.store.user_msg_for_topic_msg(t.id, m.reply_to_message.message_id)
            if target:
                reply = ReplyParameters(message_id=target, allow_sending_without_reply=True)
        try:
            sent = await self.bot.copy_message(t.user_id, self.chat, m.message_id, reply_parameters=reply)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            reason = "клиент заблокировал бота" if isinstance(e, TelegramForbiddenError) else str(e)
            await m.reply(f"⚠️ <b>Не доставлено клиенту</b>: {escape(reason)}")
            log.error("доставка #%s: %s", t.num, e)
            return
        await self.store.add_message(t.id, "out", m.from_user.id, sent.message_id, m.message_id, message_text(m))
        fields = {"status": PENDING, "last_agent_at": now()}
        if t.status == CLOSED:
            fields["closed_at"] = None
            await self._topic_state(t, closed=False)
        if not t.assignee_id:
            fields.update(assignee_id=m.from_user.id, assignee_name=m.from_user.full_name)
        await self.store.update(t.id, **fields)
        if t.status != PENDING or not t.assignee_id:
            await self.refresh(await self.store.get(t.id))

    # --- действия операторов ---

    async def _note(self, t: Ticket, text: str) -> None:
        if t.topic_id:
            try:
                await self.bot.send_message(self.chat, text, message_thread_id=t.topic_id)
            except TelegramBadRequest as e:
                log.warning("note #%s: %s", t.num, e)

    async def close(self, t: Ticket, by_name: str | None, auto: bool = False) -> None:
        if t.status == CLOSED:
            return
        await self.store.update(t.id, status=CLOSED, closed_at=now(), auto_closed=int(auto))
        t = await self.store.get(t.id)
        text = (texts.AUTO_CLOSED_CLIENT.format(num=t.num, hours=self.cfg.auto_close_hours)
                if auto else texts.CLOSED_CLIENT.format(num=t.num))
        try:
            await self.bot.send_message(t.user_id, text)
            if self.cfg.ask_rating and t.rating is None:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=f"{n}⭐", callback_data=f"rate:{t.id}:{n}") for n in range(1, 6)
                ]])
                await self.bot.send_message(t.user_id, texts.RATE_ASK, reply_markup=kb)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            log.info("уведомление о закрытии #%s: %s", t.num, e)
        who = "автоматически" if auto else escape(by_name or "оператором")
        await self._note(t, f"✅ Закрыт {who}")
        await self.refresh(t)
        await self._topic_state(t, closed=True)

    async def reopen(self, t: Ticket, by_name: str) -> None:
        if t.status != CLOSED:
            return
        await self.store.update(t.id, status=OPEN, closed_at=None)
        t = await self.store.get(t.id)
        await self._topic_state(t, closed=False)
        await self.refresh(t)
        await self._note(t, f"↩️ Открыт: {escape(by_name)}")

    async def take(self, t: Ticket, agent_id: int, agent_name: str) -> None:
        await self.store.update(t.id, assignee_id=agent_id, assignee_name=agent_name)
        await self.refresh(await self.store.get(t.id))

    async def auto_close(self) -> int:
        if self.cfg.auto_close_hours <= 0:
            return 0
        stale = await self.store.stale_pending(now() - self.cfg.auto_close_hours * 3600)
        for t in stale:
            await self.close(t, None, auto=True)
        return len(stale)
