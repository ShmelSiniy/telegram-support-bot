import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from .config import Settings
from .db import Store
from .handlers import client, staff
from .health import Health
from .service import Service
from .solo import Solo

log = logging.getLogger("supportbot")


async def auto_close_loop(service: Service) -> None:
    while True:
        try:
            n = await service.auto_close()
            if n:
                log.info("автозакрыто тикетов: %s", n)
        except Exception:
            log.exception("auto_close")
        await asyncio.sleep(1800)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Settings()
    store = Store(cfg.db_path)
    await store.open(cfg.ticket_start)
    solo = Solo(cfg.solo_dsn)
    await solo.open()

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    service = Service(bot, store, solo, cfg)
    dp = Dispatcher(store=store, service=service, settings=cfg)
    dp.include_router(staff.setup(cfg.forum_chat_id))
    dp.include_router(client.router)

    await bot.set_my_commands([BotCommand(command="start", description="Начать")],
                              scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(
        [BotCommand(command=c, description=d) for c, d in (
            ("open", "Активные тикеты"), ("stats", "Статистика"), ("close", "Закрыть тикет"),
            ("reopen", "Открыть тикет"), ("take", "Взять себе"), ("note", "Заметка"),
            ("card", "Обновить карточку"), ("ban", "Заблокировать"), ("unban", "Разблокировать"),
            ("help", "Справка"))],
        scope=BotCommandScopeChat(chat_id=cfg.forum_chat_id),
    )

    task = asyncio.create_task(auto_close_loop(service))
    health = Health()
    health_task = health_server = None
    if cfg.health_host:
        health_server = await health.serve(cfg.health_host, cfg.health_port)
        health_task = asyncio.create_task(health.heartbeat(bot))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        task.cancel()
        if health_task:
            health_task.cancel()
        if health_server:
            health_server.close()
        await solo.close()
        await store.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
