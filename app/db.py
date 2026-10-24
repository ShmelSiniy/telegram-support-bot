"""Локальное хранилище тикетов (SQLite). Все запросы параметризованы."""

import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

OPEN = "open"  # ждёт ответа оператора
PENDING = "pending"  # оператор ответил, ждём клиента
CLOSED = "closed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    user_name      TEXT NOT NULL DEFAULT '',
    username       TEXT,
    topic_id       INTEGER,
    card_msg_id    INTEGER,
    status         TEXT NOT NULL DEFAULT 'open',
    assignee_id    INTEGER,
    assignee_name  TEXT,
    rating         INTEGER,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    last_client_at INTEGER,
    last_agent_at  INTEGER,
    closed_at      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tickets_user ON tickets(user_id, status);
CREATE INDEX IF NOT EXISTS ix_tickets_topic ON tickets(topic_id);
CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets(status, last_agent_at);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    direction    TEXT NOT NULL,          -- in | out | note
    author_id    INTEGER,
    user_msg_id  INTEGER,                -- id сообщения в чате клиента
    topic_msg_id INTEGER,                -- id сообщения в теме форума
    text         TEXT,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_ticket ON messages(ticket_id);
CREATE INDEX IF NOT EXISTS ix_messages_topic ON messages(ticket_id, topic_msg_id);
CREATE INDEX IF NOT EXISTS ix_messages_user ON messages(ticket_id, user_msg_id);

CREATE TABLE IF NOT EXISTS bans (
    user_id    INTEGER PRIMARY KEY,
    reason     TEXT,
    banned_by  INTEGER,
    created_at INTEGER NOT NULL
);
"""


@dataclass
class Ticket:
    id: int
    user_id: int
    user_name: str
    username: str | None
    topic_id: int | None
    card_msg_id: int | None
    status: str
    assignee_id: int | None
    assignee_name: str | None
    rating: int | None
    created_at: int
    updated_at: int
    last_client_at: int | None
    last_agent_at: int | None
    closed_at: int | None
    auto_closed: int = 0

    @property
    def num(self) -> str:
        return f"T{self.id:06d}"


def now() -> int:
    return int(time.time())


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def open(self, ticket_start: int = 0) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(SCHEMA)
        cols = [r[1] for r in await (await self.conn.execute("PRAGMA table_info(tickets)")).fetchall()]
        if "auto_closed" not in cols:
            await self.conn.execute("ALTER TABLE tickets ADD COLUMN auto_closed INTEGER NOT NULL DEFAULT 0")
        if ticket_start > 0:
            # Продолжаем нумерацию старого бота, только если тикетов ещё не было.
            cur = await self.conn.execute("SELECT seq FROM sqlite_sequence WHERE name='tickets'")
            row = await cur.fetchone()
            if row is None:
                await self.conn.execute(
                    "INSERT INTO sqlite_sequence(name, seq) VALUES ('tickets', ?)", (ticket_start,)
                )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # --- tickets ---

    async def _one(self, sql: str, args: tuple) -> Ticket | None:
        cur = await self.conn.execute(sql, args)
        row = await cur.fetchone()
        return Ticket(**dict(row)) if row else None

    async def get(self, ticket_id: int) -> Ticket | None:
        return await self._one("SELECT * FROM tickets WHERE id=?", (ticket_id,))

    async def by_topic(self, topic_id: int) -> Ticket | None:
        return await self._one("SELECT * FROM tickets WHERE topic_id=? ORDER BY id DESC LIMIT 1", (topic_id,))

    async def active_for_user(self, user_id: int) -> Ticket | None:
        return await self._one(
            "SELECT * FROM tickets WHERE user_id=? AND status!=? ORDER BY id DESC LIMIT 1", (user_id, CLOSED)
        )

    async def last_closed_for_user(self, user_id: int) -> Ticket | None:
        return await self._one(
            "SELECT * FROM tickets WHERE user_id=? AND status=? ORDER BY closed_at DESC LIMIT 1", (user_id, CLOSED)
        )

    async def create(self, user_id: int, user_name: str, username: str | None) -> Ticket:
        ts = now()
        cur = await self.conn.execute(
            "INSERT INTO tickets(user_id, user_name, username, status, created_at, updated_at, last_client_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, user_name, username, OPEN, ts, ts, ts),
        )
        await self.conn.commit()
        return await self.get(cur.lastrowid)

    async def update(self, ticket_id: int, **fields) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)  # ключи — только из кода, не из ввода
        await self.conn.execute(f"UPDATE tickets SET {cols} WHERE id=?", (*fields.values(), ticket_id))
        await self.conn.commit()

    async def list_active(self, limit: int = 50) -> list[Ticket]:
        cur = await self.conn.execute(
            "SELECT * FROM tickets WHERE status!=? ORDER BY status='open' DESC, last_client_at ASC LIMIT ?",
            (CLOSED, limit),
        )
        return [Ticket(**dict(r)) for r in await cur.fetchall()]

    async def stale_pending(self, older_than: int) -> list[Ticket]:
        cur = await self.conn.execute(
            "SELECT * FROM tickets WHERE status=? AND last_agent_at IS NOT NULL AND last_agent_at < ?",
            (PENDING, older_than),
        )
        return [Ticket(**dict(r)) for r in await cur.fetchall()]

    async def stats(self, since: int) -> dict:
        cur = await self.conn.execute(
            "SELECT "
            " SUM(status='open'), SUM(status='pending'),"
            " SUM(created_at>=?), SUM(closed_at>=?),"
            " AVG(rating), COUNT(rating) "
            "FROM tickets",
            (since, since),
        )
        r = await cur.fetchone()
        return {
            "open": r[0] or 0,
            "pending": r[1] or 0,
            "created": r[2] or 0,
            "closed": r[3] or 0,
            "avg_rating": r[4],
            "rated": r[5] or 0,
        }

    # --- messages ---

    async def add_message(
        self,
        ticket_id: int,
        direction: str,
        author_id: int | None,
        user_msg_id: int | None,
        topic_msg_id: int | None,
        text: str | None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO messages(ticket_id, direction, author_id, user_msg_id, topic_msg_id, text, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (ticket_id, direction, author_id, user_msg_id, topic_msg_id, text, now()),
        )
        await self.conn.commit()

    async def user_msg_for_topic_msg(self, ticket_id: int, topic_msg_id: int) -> int | None:
        cur = await self.conn.execute(
            "SELECT user_msg_id FROM messages WHERE ticket_id=? AND topic_msg_id=? AND user_msg_id IS NOT NULL",
            (ticket_id, topic_msg_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def topic_msg_for_user_msg(self, ticket_id: int, user_msg_id: int) -> int | None:
        cur = await self.conn.execute(
            "SELECT topic_msg_id FROM messages WHERE ticket_id=? AND user_msg_id=? AND topic_msg_id IS NOT NULL",
            (ticket_id, user_msg_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def recent_messages(self, ticket_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT direction, text, created_at FROM messages WHERE ticket_id=? AND direction!='note' "
            "ORDER BY id DESC LIMIT ?",
            (ticket_id, limit),
        )
        return list(reversed(await cur.fetchall()))

    # --- bans ---

    async def is_banned(self, user_id: int) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM bans WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None

    async def ban(self, user_id: int, reason: str | None, by: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO bans(user_id, reason, banned_by, created_at) VALUES (?,?,?,?)",
            (user_id, reason, by, now()),
        )
        await self.conn.commit()

    async def unban(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM bans WHERE user_id=?", (user_id,))
        await self.conn.commit()
