import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Message, User as TelegramUser
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.middlewares import EventLoggingMiddleware
from app.bot.routers import build_router
from app.config import Settings


class LogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def log_capture():
    logger = logging.getLogger("app.bot.events")
    logger.setLevel(logging.DEBUG)
    handler = LogCaptureHandler()
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


@pytest.mark.asyncio
async def test_event_logging_middleware_message(log_capture):
    middleware = EventLoggingMiddleware("telegram")
    user = TelegramUser(id=12345, is_bot=False, first_name="Ali", last_name="Rezaei", username="alirez")
    message = MagicMock(spec=Message)
    message.message_id = 99
    message.from_user = user
    message.text = "/start"
    message.document = None

    handler = AsyncMock(return_value="handler_result")
    data = {}

    result = await middleware(handler, message, data)

    assert result == "handler_result"
    handler.assert_awaited_once_with(message, data)
    assert any("Incoming Message(id=99, text=\"/start\") from user_id=12345" in msg for msg in log_capture.messages)
    assert any("Handled Message(id=99, text=\"/start\")" in msg for msg in log_capture.messages)


@pytest.mark.asyncio
async def test_event_logging_middleware_callback(log_capture):
    middleware = EventLoggingMiddleware("bale")
    user = TelegramUser(id=67890, is_bot=False, first_name="Sara", last_name=None, username=None)
    callback = MagicMock(spec=CallbackQuery)
    callback.data = "adm:home"
    callback.from_user = user
    callback.message = MagicMock(message_id=42)

    handler = AsyncMock(return_value="callback_result")
    data = {}

    result = await middleware(handler, callback, data)

    assert result == "callback_result"
    handler.assert_awaited_once_with(callback, data)
    assert any("Incoming CallbackQuery(data=\"adm:home\", msg_id=42)" in msg for msg in log_capture.messages)
    assert any("Handled CallbackQuery(data=\"adm:home\", msg_id=42)" in msg for msg in log_capture.messages)


@pytest.mark.asyncio
async def test_event_logging_middleware_exception_logging(log_capture):
    middleware = EventLoggingMiddleware("telegram")
    user = TelegramUser(id=12345, is_bot=False, first_name="Ali", username=None)
    message = MagicMock(spec=Message)
    message.message_id = 100
    message.from_user = user
    message.text = "boom"
    message.document = None

    handler = AsyncMock(side_effect=RuntimeError("something went wrong"))
    data = {}

    with pytest.raises(RuntimeError, match="something went wrong"):
        await middleware(handler, message, data)

    assert any("Exception while handling Message(id=100, text=\"boom\")" in msg for msg in log_capture.messages)


def test_build_router_includes_event_logging_middleware():
    session_factory = MagicMock(spec=async_sessionmaker)
    settings = Settings(bot_token="test:token", bot_platform="telegram", admin_user_ids="123")
    router = build_router(session_factory, settings)

    assert any(isinstance(mw, EventLoggingMiddleware) for mw in router.message.outer_middleware)
    assert any(isinstance(mw, EventLoggingMiddleware) for mw in router.callback_query.outer_middleware)


def test_setup_logging_creates_safe_stream_and_rotating_file(tmp_path):
    from app.logging_config import SafeStreamHandler, setup_logging

    log_file = tmp_path / "test_bot.log"
    setup_logging(log_level="INFO", log_file=log_file)

    root = logging.getLogger()
    assert any(isinstance(h, SafeStreamHandler) for h in root.handlers)
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers)

    test_logger = logging.getLogger("app.test")
    test_msg = "پیام آزمایشی فارسی برای بررسی لاگ سرتاسری"
    test_logger.info(test_msg)

    # Flush all handlers
    for h in root.handlers:
        h.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert test_msg in content
    assert "[app.test]" in content

