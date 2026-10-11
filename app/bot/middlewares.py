import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger("app.bot.events")


class EventLoggingMiddleware(BaseMiddleware):
    """Logs every incoming Telegram/Bale message and callback query with duration and context."""

    def __init__(self, platform: str) -> None:
        self.platform = platform

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        start_time = time.perf_counter()
        user_info = "unknown"
        event_desc = "unknown"

        if isinstance(event, Message):
            user = event.from_user
            if user:
                user_info = f"user_id={user.id} (@{user.username or 'none'}, {user.full_name})"
            if event.text:
                event_desc = f'Message(id={event.message_id}, text="{event.text}")'
            elif event.document:
                event_desc = (
                    f'Document(id={event.message_id}, name="{event.document.file_name}", '
                    f'size={event.document.file_size})'
                )
            else:
                event_desc = f"Message(id={event.message_id}, content_type={event.content_type})"
            logger.info("[%s] Incoming %s from %s", self.platform, event_desc, user_info)

        elif isinstance(event, CallbackQuery):
            user = event.from_user
            if user:
                user_info = f"user_id={user.id} (@{user.username or 'none'}, {user.full_name})"
            msg_id = event.message.message_id if event.message else None
            event_desc = f'CallbackQuery(data="{event.data}", msg_id={msg_id})'
            logger.info("[%s] Incoming %s from %s", self.platform, event_desc, user_info)

        try:
            result = await handler(event, data)
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.debug("[%s] Handled %s for %s in %.1fms", self.platform, event_desc, user_info, duration_ms)
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "[%s] Exception while handling %s for %s after %.1fms: %s",
                self.platform,
                event_desc,
                user_info,
                duration_ms,
                exc,
                exc_info=True,
            )
            raise
