from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def initialize_database() -> None:
    async with engine.begin() as connection:
        tables = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
        if "users" in tables:
            columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"] for column in inspect(sync_connection).get_columns("users")
                }
            )
            if "platform" not in columns:
                await connection.execute(
                    text("ALTER TABLE users ADD COLUMN platform VARCHAR(16) NOT NULL DEFAULT 'telegram'")
                )
            if "telegram_id" in columns and "platform_user_id" not in columns:
                await connection.execute(
                    text("ALTER TABLE users RENAME COLUMN telegram_id TO platform_user_id")
                )
            if engine.dialect.name == "postgresql":
                await connection.execute(text(
                    "ALTER TABLE users ALTER COLUMN platform_user_id TYPE BIGINT"
                ))
            await connection.execute(text("DROP INDEX IF EXISTS ix_users_telegram_id"))
            await connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_platform_platform_user_id "
                "ON users (platform, platform_user_id)"
            ))
        await connection.run_sync(Base.metadata.create_all)
