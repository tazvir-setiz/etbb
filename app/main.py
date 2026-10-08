import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from app.bot.routers import build_router
from app.config import ENV_FILE, get_settings
from app.database import SessionFactory, engine, initialize_database


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError(
            f"BOT_TOKEN is empty. Put your bot token in {ENV_FILE} "
            "(copy .env.example first) or set the BOT_TOKEN environment variable."
        )
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await initialize_database()
    session = None
    if settings.bot_platform == "bale":
        session = AiohttpSession(api=TelegramAPIServer.from_base("https://tapi.bale.ai"))
    bot = Bot(settings.bot_token, session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(SessionFactory, settings))
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
