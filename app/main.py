import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers import build_router
from app.config import get_settings
from app.database import SessionFactory, engine, initialize_database


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required. Copy .env.example to .env and configure it.")
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await initialize_database()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(SessionFactory, settings))
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
