from aiogram import F, Router
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.routers.admin import build_admin_router
from app.bot.routers.user import build_user_router
from app.config import Settings


def build_router(session_factory: async_sessionmaker, settings: Settings) -> Router:
    router = Router()
    # Admin routes get a dedicated menu and authorization checks on each action.
    router.include_router(build_admin_router(session_factory, settings))
    router.include_router(build_user_router(session_factory, settings))

    fallback = Router(name="fallback")

    @fallback.callback_query(F.data == "noop")
    async def noop(callback):
        await callback.answer()

    @fallback.callback_query()
    async def stale_callback(callback):
        await callback.answer("این دکمه دیگر فعال نیست. از منو دوباره انتخاب کنید.", show_alert=True)

    @fallback.message()
    async def unknown_message(message):
        await message.answer("این پیام را نمی‌شناسم. از گزینه‌های منو استفاده کنید یا /start را بفرستید.")

    router.include_router(fallback)
    return router
