import asyncio

from app import health
from app.health import Health


def run(coro):
    return asyncio.run(coro)


async def _get(port: int) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    await writer.drain()
    data = await reader.read()
    writer.close()
    return data


def test_unhealthy_until_first_heartbeat_then_healthy():
    h = Health()
    assert not h.healthy
    h.last_ok = health.time.monotonic()
    assert h.healthy
    h.last_ok = health.time.monotonic() - health.STALE_AFTER - 1
    assert not h.healthy


def test_endpoint_status_follows_health():
    async def go():
        h = Health()
        server = await h.serve("127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        assert b" 503 " in (await _get(port)).split(b"\r\n")[0] + b" "
        h.last_ok = health.time.monotonic()
        first = (await _get(port)).split(b"\r\n")[0]
        server.close()
        await server.wait_closed()
        return first

    assert run(go()).startswith(b"HTTP/1.1 200")
