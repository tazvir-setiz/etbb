from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def initialize_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
