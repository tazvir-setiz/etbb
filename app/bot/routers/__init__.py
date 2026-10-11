import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.middlewares import EventLoggingMiddleware
from app.bot.routers.admin import build_admin_router
from app.bot.routers.user import build_user_router
from app.config import Settings

logger = logging.getLogger(__name__)


def build_router(session_factory: async_sessionmaker, settings: Settings) -> Router:
    router = Router()
    logging_middleware = EventLoggingMiddleware(settings.bot_platform)
    router.message.outer_middleware(logging_middleware)
    router.callback_query.outer_middleware(logging_middleware)

    # Admin routes get a dedicated menu and authorization checks on each action.
    router.include_router(build_admin_router(session_factory, settings))
    router.include_router(build_user_router(session_factory, settings))

    fallback = Router(name="fallback")

    @fallback.callback_query(F.data == "noop")
    async def noop(callback: CallbackQuery) -> None:
        await callback.answer()

    @fallback.callback_query()
    async def stale_callback(callback: CallbackQuery) -> None:
        logger.warning(
            "[%s] Stale callback received from user %s: data=%s",
            settings.bot_platform,
            callback.from_user.id if callback.from_user else "unknown",
            callback.data,
        )
        await callback.answer("این دکمه دیگر فعال نیست. از منو دوباره انتخاب کنید.", show_alert=True)

    @fallback.message()
    async def unknown_message(message: Message) -> None:
        logger.warning(
            "[%s] Unrecognized message received from user %s: text=%r",
            settings.bot_platform,
            message.from_user.id if message.from_user else "unknown",
            message.text,
        )
        await message.answer("این پیام را نمی‌شناسم. از گزینه‌های منو استفاده کنید یا /start را بفرستید.")

    router.include_router(fallback)

    @router.errors()
    async def global_error_handler(event: ErrorEvent) -> bool:
        logger.exception(
            "[%s] خطای غیرمنتظره در پردازش پیام/رویداد (update_id=%s): %s",
            settings.bot_platform,
            event.update.update_id if event.update else "none",
            event.exception,
            exc_info=event.exception,
        )
        try:
            if event.update.message:
                await event.update.message.answer(
                    "متأسفانه در اجرای درخواست شما خطایی رخ داد. لطفاً دوباره تلاش کنید یا با /cancel روند را لغو کنید."
                )
            elif event.update.callback_query:
                await event.update.callback_query.answer(
                    "خطایی رخ داد. لطفاً دوباره امتحان کنید.", show_alert=True
                )
        except Exception:
            pass
        return True
    return router
