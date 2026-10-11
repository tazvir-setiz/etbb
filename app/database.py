import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def initialize_database() -> None:
    alembic_ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    logger.info("Initializing database: running Alembic migrations using %s", alembic_ini_path)
    config = Config(str(alembic_ini_path))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

    def upgrade(sync_connection) -> None:
        config.attributes["connection"] = sync_connection
        command.upgrade(config, "head")

    async with engine.connect() as connection:
        await connection.run_sync(upgrade)
    logger.info("Database migrations applied successfully.")
