import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.telegram import TelegramAPIServer

from app.bot.routers import build_router
from app.bot.session import BaleAiohttpSession
from app.config import ENV_FILE, get_settings
from app.database import SessionFactory, engine, initialize_database
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def check_system() -> bool:
    """Diagnostic self-check for database connection and migration status."""
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)
    logger.info("Running system diagnostics on platform: %s...", settings.bot_platform)
    try:
        await initialize_database()
        logger.info("System check succeeded: database migrations are up to date.")
        return True
    except Exception as exc:
        logger.error("System check failed with error: %s", exc)
        return False


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError(
            f"BOT_TOKEN is empty. Put your bot token in {ENV_FILE} "
            "(copy .env.example first) or set the BOT_TOKEN environment variable."
        )
    setup_logging(settings.log_level, settings.log_file)
    logger.info("Starting survey bot on platform: %s (Timezone: %s)", settings.bot_platform, settings.timezone)
    await initialize_database()
    logger.info("Database initialized successfully.")
    session = None
    if settings.bot_platform == "bale":
        session = BaleAiohttpSession(api=TelegramAPIServer.from_base("https://tapi.bale.ai"))
    bot = Bot(settings.bot_token, session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(SessionFactory, settings))
    try:
        try:
            bot_user = await bot.get_me()
            logger.info(
                "[%s] Connected to Bot API. Bot user: @%s (id=%s, name='%s')",
                settings.bot_platform,
                bot_user.username,
                bot_user.id,
                bot_user.first_name,
            )
        except Exception as exc:
            logger.warning("[%s] Could not fetch bot user details at startup: %s", settings.bot_platform, exc)
        logger.info("[%s] Starting polling...", settings.bot_platform)
        await dispatcher.start_polling(bot)
    finally:
        logger.info("Shutting down bot session and database engine...")
        await bot.session.close()
        await engine.dispose()
        logger.info("Shutdown completed.")


if __name__ == "__main__":
    if "--check" in sys.argv:
        success = asyncio.run(check_system())
        sys.exit(0 if success else 1)
    asyncio.run(main())

