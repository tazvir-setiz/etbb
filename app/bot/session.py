from __future__ import annotations

import logging

from aiohttp import FormData
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import InputFile

logger = logging.getLogger(__name__)


class BaleAiohttpSession(AiohttpSession):
    """Bale-compatible AiohttpSession that places top-level InputFiles directly in named multipart fields.

    The Bale Bot API (https://tapi.bale.ai) does not support the Telegram Bot API 4.0+
    'attach://<token>' indirection for direct file uploads (e.g. sendDocument, sendPhoto).
    Instead, Bale treats 'attach://...' as an external HTTP URL and fails with:
    'Bad Request: failed to get HTTP URL content'.

    This session overrides build_form_data to attach top-level InputFile instances directly
    under their respective parameter names (e.g. 'document', 'photo') in multipart/form-data.
    """

    def build_form_data(self, bot: Bot, method: TelegramMethod[TelegramType]) -> FormData:
        form = FormData(quote_fields=False)
        files: dict[str, InputFile] = {}
        for key, value in method.model_dump(warnings=False).items():
            if isinstance(value, InputFile):
                form.add_field(
                    key,
                    value.read(bot),
                    filename=value.filename or key,
                )
                continue
            prepared = self.prepare_value(value, bot=bot, files=files)
            if prepared is None:
                continue
            form.add_field(key, prepared)
        for key, value in files.items():
            form.add_field(
                key,
                value.read(bot),
                filename=value.filename or key,
            )
        return form
