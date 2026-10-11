import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import AdminDraft

logger = logging.getLogger(__name__)


async def save_admin_draft(
    session_factory: async_sessionmaker,
    *,
    platform: str,
    platform_user_id: int,
    draft_type: str,
    step: str,
    payload: dict[str, Any],
) -> None:
    logger.debug(
        "[%s] Saving admin draft for user %s: type=%s, step=%s",
        platform,
        platform_user_id,
        draft_type,
        step,
    )
    values = {
        "platform": platform,
        "platform_user_id": platform_user_id,
        "draft_type": draft_type,
        "step": step,
        "payload": payload,
    }
    async with session_factory() as session:
        dialect = session.bind.dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(AdminDraft).values(**values)
        elif dialect == "postgresql":
            statement = postgresql_insert(AdminDraft).values(**values)
        else:
            raise ValueError(f"Unsupported database for admin drafts: {dialect}")
        statement = statement.on_conflict_do_update(
            index_elements=[AdminDraft.platform, AdminDraft.platform_user_id],
            set_={
                "draft_type": draft_type,
                "step": step,
                "payload": payload,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(statement)
        await session.commit()


async def get_admin_draft(
    session_factory: async_sessionmaker,
    *,
    platform: str,
    platform_user_id: int,
) -> AdminDraft | None:
    async with session_factory() as session:
        draft = await session.scalar(
            select(AdminDraft).where(
                AdminDraft.platform == platform,
                AdminDraft.platform_user_id == platform_user_id,
            )
        )
        logger.debug(
            "[%s] Fetched admin draft for user %s: exists=%s, type=%s",
            platform,
            platform_user_id,
            draft is not None,
            draft.draft_type if draft else None,
        )
        return draft


async def delete_admin_draft(
    session_factory: async_sessionmaker,
    *,
    platform: str,
    platform_user_id: int,
) -> None:
    logger.debug("[%s] Deleting admin draft for user %s", platform, platform_user_id)
    async with session_factory() as session:
        await session.execute(
            delete(AdminDraft).where(
                AdminDraft.platform == platform,
                AdminDraft.platform_user_id == platform_user_id,
            )
        )
        await session.commit()
