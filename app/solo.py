"""Только чтение данных клиента из базы SOLObot. Ошибки не роняют бота — карточка просто беднее."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg

log = logging.getLogger(__name__)


@dataclass
class SoloKey:
    name: str
    expires: datetime | None
    frozen: bool
    server: str | None
    link: str | None
    tariff: str | None
    devices: int | None
    traffic_gb: int | None
    used_gb: float | None


@dataclass
class SoloPayment:
    amount: float
    system: str
    status: str
    at: datetime | None


@dataclass
class SoloProfile:
    found: bool
    balance: float | None = None
    registered: datetime | None = None
    trial: int | None = None
    source: str | None = None
    email: str | None = None
    banned_until: datetime | None = None
    ban_reason: str | None = None
    blocked_bot: bool = False
    keys: list[SoloKey] = field(default_factory=list)
    payments: list[SoloPayment] = field(default_factory=list)
    paid_total: float = 0.0


def _ms(v: int | None) -> datetime | None:
    return datetime.fromtimestamp(v / 1000) if v else None


class Solo:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def open(self) -> None:
        if not self.dsn:
            return
        try:
            self.pool = await asyncpg.create_pool(
                self.dsn, min_size=0, max_size=3, command_timeout=5,
                server_settings={"default_transaction_read_only": "on"},
            )
        except Exception as e:
            log.error("SOLObot DB недоступна: %s", e)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def profile(self, tg_id: int) -> SoloProfile | None:
        """None — интеграция выключена или упала; SoloProfile(found=False) — клиента нет в SOLObot."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as c:
                u = await c.fetchrow(
                    "SELECT u.balance, u.created_at, u.trial, u.source_code, i.email "
                    "FROM users u LEFT JOIN identities i ON i.id = u.identity_id WHERE u.tg_id=$1",
                    tg_id,
                )
                if not u:
                    return SoloProfile(found=False)
                p = SoloProfile(
                    found=True,
                    balance=u["balance"],
                    registered=u["created_at"],
                    trial=u["trial"],
                    source=u["source_code"],
                    email=u["email"],
                )
                keys = await c.fetch(
                    "SELECT k.email, k.alias, k.client_id, k.expiry_time, k.is_frozen, k.server_id, "
                    "       k.remnawave_link, k.current_device_limit, k.current_traffic_limit, t.name AS tariff, "
                    "       (SELECT h.used_gb FROM key_traffic_history h WHERE h.client_id=k.client_id "
                    "        ORDER BY h.snapshot_date DESC LIMIT 1) AS used_gb "
                    "FROM keys k LEFT JOIN tariffs t ON t.id=k.tariff_id "
                    "WHERE k.tg_id=$1 ORDER BY k.expiry_time DESC LIMIT 5",
                    tg_id,
                )
                p.keys = [
                    SoloKey(
                        name=k["alias"] or k["email"] or k["client_id"],
                        expires=_ms(k["expiry_time"]),
                        frozen=bool(k["is_frozen"]),
                        server=k["server_id"],
                        link=k["remnawave_link"],
                        tariff=k["tariff"],
                        devices=k["current_device_limit"],
                        traffic_gb=k["current_traffic_limit"],
                        used_gb=k["used_gb"],
                    )
                    for k in keys
                ]
                pays = await c.fetch(
                    "SELECT amount, payment_system, status, created_at FROM payments "
                    "WHERE tg_id=$1 ORDER BY created_at DESC LIMIT 3",
                    tg_id,
                )
                p.payments = [SoloPayment(r["amount"], r["payment_system"], r["status"], r["created_at"]) for r in pays]
                p.paid_total = float(
                    await c.fetchval(
                        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE tg_id=$1 AND status='success'", tg_id
                    )
                )
                ban = await c.fetchrow(
                    "SELECT until, reason FROM manual_bans WHERE tg_id=$1 AND (until IS NULL OR until > now())",
                    tg_id,
                )
                if ban:
                    p.banned_until = ban["until"] or datetime.max
                    p.ban_reason = ban["reason"]
                p.blocked_bot = bool(await c.fetchval("SELECT 1 FROM blocked_users WHERE tg_id=$1", tg_id))
                return p
        except Exception as e:
            log.error("SOLObot профиль %s: %s", tg_id, e)
            return None
