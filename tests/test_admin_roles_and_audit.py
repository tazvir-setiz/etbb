from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import AdminRole, Base
from app.services.admin_roles import (
    AdminRoleError,
    add_admin_user,
    get_user_role,
    list_admin_users,
    remove_admin_user,
    update_admin_role,
)
from app.services.audit import list_audit_logs, record_audit_log


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test_admin.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_and_get_user_role(session_factory):
    async with session_factory() as session:
        role = await get_user_role(
            session,
            platform="telegram",
            platform_user_id=1001,
            initial_admin_ids={1001},
        )
        assert role == AdminRole.OWNER

        role_non_admin = await get_user_role(
            session,
            platform="telegram",
            platform_user_id=9999,
            initial_admin_ids={1001},
        )
        assert role_non_admin is None


@pytest.mark.asyncio
async def test_add_and_list_admin_users(session_factory):
    async with session_factory() as session:
        # Bootstrap owner
        await add_admin_user(
            session,
            platform="telegram",
            platform_user_id=1001,
            role=AdminRole.OWNER,
            actor_id=1001,
        )
        # Add normal admin
        admin2 = await add_admin_user(
            session,
            platform="telegram",
            platform_user_id=1002,
            role=AdminRole.ADMIN,
            actor_id=1001,
        )
        assert admin2.role == AdminRole.ADMIN.value

        admins = await list_admin_users(session, platform="telegram")
        assert len(admins) == 2

        # Duplicate addition rejected
        with pytest.raises(AdminRoleError, match="در حال حاضر دسترسی مدیریتی دارد"):
            await add_admin_user(
                session,
                platform="telegram",
                platform_user_id=1002,
                role=AdminRole.ADMIN,
                actor_id=1001,
            )


@pytest.mark.asyncio
async def test_last_owner_protection(session_factory):
    async with session_factory() as session:
        await add_admin_user(
            session,
            platform="telegram",
            platform_user_id=1001,
            role=AdminRole.OWNER,
            actor_id=1001,
        )
        await add_admin_user(
            session,
            platform="telegram",
            platform_user_id=1002,
            role=AdminRole.ADMIN,
            actor_id=1001,
        )

        # Cannot demote last owner
        with pytest.raises(AdminRoleError, match="آخرین مالک"):
            await update_admin_role(
                session,
                platform="telegram",
                platform_user_id=1001,
                new_role=AdminRole.ADMIN,
                actor_id=1001,
            )

        # Cannot remove last owner
        with pytest.raises(AdminRoleError, match="آخرین مالک"):
            await remove_admin_user(
                session,
                platform="telegram",
                platform_user_id=1001,
                actor_id=1001,
            )

        # Promoting 1002 to owner
        await update_admin_role(
            session,
            platform="telegram",
            platform_user_id=1002,
            new_role=AdminRole.OWNER,
            actor_id=1001,
        )
        role = await get_user_role(session, platform="telegram", platform_user_id=1002)
        assert role == AdminRole.OWNER

        # Now 1001 can be demoted because 1002 is also an owner
        await update_admin_role(
            session,
            platform="telegram",
            platform_user_id=1001,
            new_role=AdminRole.ADMIN,
            actor_id=1002,
        )
        role1 = await get_user_role(session, platform="telegram", platform_user_id=1001)
        assert role1 == AdminRole.ADMIN

        # Remove 1001
        await remove_admin_user(
            session,
            platform="telegram",
            platform_user_id=1001,
            actor_id=1002,
        )
        assert await get_user_role(session, platform="telegram", platform_user_id=1001) is None


@pytest.mark.asyncio
async def test_audit_logging_and_privacy_guarantee(session_factory):
    async with session_factory() as session:
        # Sensitive voter info in details must be stripped
        log = await record_audit_log(
            session,
            platform="telegram",
            actor_id=1001,
            action="SURVEY_CANCEL",
            target_type="survey",
            target_id="5",
            details={
                "title": "نظرسنجی تستی",
                "voter_id": 9999,
                "scores": [5, 4, 3],
            },
        )
        assert log.id is not None
        assert "voter_id" not in log.details
        assert "scores" not in log.details
        assert log.details.get("title") == "نظرسنجی تستی"

        logs, total = await list_audit_logs(session, platform="telegram", limit=10)
        assert total >= 1
        assert any(entry.action == "SURVEY_CANCEL" for entry in logs)


@pytest.mark.asyncio
async def test_alembic_migration_creates_new_tables(tmp_path):
    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", db_url)

    engine = create_async_engine(db_url)

    def upgrade(sync_conn):
        config.attributes["connection"] = sync_conn
        command.upgrade(config, "head")

    async with engine.connect() as conn:
        await conn.run_sync(upgrade)

    await engine.dispose()

    # Verify tables with sync engine
    from sqlalchemy import create_engine, inspect

    sync_engine = create_engine(f"sqlite:///{db_file}")
    table_names = set(inspect(sync_engine).get_table_names())
    assert "admin_users" in table_names
    assert "audit_logs" in table_names
    assert "users" in table_names
    assert "surveys" in table_names
    sync_engine.dispose()
