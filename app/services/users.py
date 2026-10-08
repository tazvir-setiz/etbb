from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def register_or_update_user(
    session: AsyncSession,
    *,
    platform: str,
    platform_user_id: int,
    full_name: str,
    username: str | None,
    is_admin: bool,
) -> None:
    values = {
        "platform": platform,
        "platform_user_id": platform_user_id,
        "full_name": full_name,
        "username": username,
        "is_admin": is_admin,
    }
    dialect = session.bind.dialect.name
    if dialect == "sqlite":
        statement = sqlite_insert(User).values(**values)
    elif dialect == "postgresql":
        statement = postgresql_insert(User).values(**values)
    else:
        raise ValueError(f"Unsupported database for user upsert: {dialect}")

    statement = statement.on_conflict_do_update(
        index_elements=[User.platform, User.platform_user_id],
        set_={"full_name": full_name, "username": username, "is_admin": is_admin},
    )
    await session.execute(statement)
    await session.commit()
