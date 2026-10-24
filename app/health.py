"""Optional health endpoint for an external watchdog (failover between hosts).

Off by default. When HEALTH_HOST is set, a tiny HTTP server answers
`GET /health` with 200 while the bot reached the Telegram API recently and
503 otherwise. Bind it to a private interface (e.g. a Tailscale address).
"""

import asyncio
import logging
import time

from aiogram import Bot

log = logging.getLogger(__name__)

HEARTBEAT_EVERY = 30   # seconds between Telegram API checks
STALE_AFTER = 120      # seconds without a successful check -> unhealthy


class Health:
    def __init__(self) -> None:
        self.last_ok = 0.0

    @property
    def healthy(self) -> bool:
        return time.monotonic() - self.last_ok < STALE_AFTER if self.last_ok else False

    async def heartbeat(self, bot: Bot) -> None:
        while True:
            try:
                await bot.get_me()
                self.last_ok = time.monotonic()
            except Exception as e:  # network down, token revoked, ...
                log.warning("health heartbeat failed: %s", e)
            await asyncio.sleep(HEARTBEAT_EVERY)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except Exception:
            writer.close()
            return
        ok = self.healthy
        body = b"ok\n" if ok else b"unhealthy\n"
        status = b"200 OK" if ok else b"503 Service Unavailable"
        writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Type: text/plain\r\n"
                     b"Content-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        try:
            await writer.drain()
        finally:
            writer.close()

    async def serve(self, host: str, port: int) -> asyncio.Server:
        server = await asyncio.start_server(self._handle, host, port)
        log.info("health endpoint on %s:%s", host, port)
        return server
