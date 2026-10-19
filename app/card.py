"""Карточка тикета — первое сообщение в теме форума."""

from datetime import datetime
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .db import CLOSED, OPEN, PENDING, Ticket
from .solo import SoloProfile

STATUS_ICON = {OPEN: "🔴", PENDING: "🟡", CLOSED: "✅"}
STATUS_TEXT = {OPEN: "ждёт ответа", PENDING: "ждём клиента", CLOSED: "закрыт"}


def _d(dt: datetime | None) -> str:
    if not dt:
        return "—"
    if dt == datetime.max:
        return "навсегда"
    return dt.strftime("%d.%m.%Y")


def topic_title(t: Ticket) -> str:
    name = t.user_name or str(t.user_id)
    tail = f" @{t.username}" if t.username else ""
    return f"{STATUS_ICON[t.status]} #{t.num} · {name}{tail}"[:128]


def render(t: Ticket, p: SoloProfile | None) -> str:
    who = escape(t.user_name or "без имени")
    lines = [
        f"<b>#{t.num}</b> · {STATUS_ICON[t.status]} {STATUS_TEXT[t.status]}",
        f'👤 <a href="tg://user?id={t.user_id}">{who}</a>'
        + (f" @{escape(t.username)}" if t.username else "")
        + f" · <code>{t.user_id}</code>",
    ]
    if t.assignee_name:
        lines.append(f"🧑‍💻 Ведёт: {escape(t.assignee_name)}")

    if p is None:
        lines.append("\n<i>Данные SOLObot недоступны</i>")
    elif not p.found:
        lines.append("\n⚠️ <b>Нет в базе SOLObot</b>")
    else:
        lines.append("")
        meta = [f"баланс {p.balance:.0f} ₽" if p.balance is not None else None,
                f"оплачено всего {p.paid_total:.0f} ₽",
                f"с {_d(p.registered)}"]
        lines.append("💳 " + " · ".join(m for m in meta if m))
        if p.email:
            lines.append(f"✉️ {escape(p.email)}")
        if p.source:
            lines.append(f"🔗 источник: {escape(p.source)}")
        if p.banned_until:
            reason = f" — {escape(p.ban_reason)}" if p.ban_reason else ""
            lines.append(f"⛔️ Бан в SOLObot до {_d(p.banned_until)}{reason}")
        if p.blocked_bot:
            lines.append("🚫 Клиент заблокировал основной бот")

        if p.keys:
            lines.append("\n<b>Подписки</b>")
            today = datetime.now()
            for k in p.keys:
                state = "❄️" if k.frozen else ("🟢" if k.expires and k.expires > today else "⚪️")
                traffic = ""
                if k.traffic_gb:
                    used = f"{k.used_gb:.0f}/" if k.used_gb is not None else ""
                    traffic = f" · {used}{k.traffic_gb} ГБ"
                dev = f" · {k.devices} устр." if k.devices else ""
                tariff = f" · {escape(k.tariff)}" if k.tariff else ""
                lines.append(f"{state} <code>{escape(k.name)}</code> до {_d(k.expires)}{tariff}{traffic}{dev}")
                if k.link:
                    lines.append(f"   <code>{escape(k.link)}</code>")
        else:
            lines.append("\nПодписок нет")

        if p.payments:
            lines.append("\n<b>Последние оплаты</b>")
            for pay in p.payments:
                ok = "✅" if pay.status == "success" else "✖️"
                lines.append(f"{ok} {pay.amount:.0f} ₽ · {escape(pay.system or '')} · {_d(pay.at)}")

    return "\n".join(lines)[:4000]


def keyboard(t: Ticket) -> InlineKeyboardMarkup:
    if t.status == CLOSED:
        row = [InlineKeyboardButton(text="↩️ Открыть", callback_data=f"t:reopen:{t.id}")]
    else:
        row = [
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"t:close:{t.id}"),
            InlineKeyboardButton(text="🙋 Взять", callback_data=f"t:take:{t.id}"),
        ]
    return InlineKeyboardMarkup(
        inline_keyboard=[row, [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"t:card:{t.id}")]]
    )
