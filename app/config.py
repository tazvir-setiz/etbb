from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    bot_token: str = ""
    bot_platform: str = "telegram"
    admin_user_ids: str = ""
    database_url: str = "sqlite+aiosqlite:///./survey_bot.db"
    timezone: str = "Asia/Tehran"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @field_validator("bot_platform")
    @classmethod
    def validate_bot_platform(cls, value: str) -> str:
        platform = value.strip().lower()
        if platform not in {"telegram", "bale"}:
            raise ValueError("BOT_PLATFORM must be either 'telegram' or 'bale'.")
        return platform

    @property
    def admin_ids(self) -> set[int]:
        return {int(value.strip()) for value in self.admin_user_ids.split(",") if value.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
