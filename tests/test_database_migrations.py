from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base


def _run_upgrade_sync(db_url: str) -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", db_url)
    engine = create_async_engine(db_url)

    def do_upgrade(sync_conn):
        config.attributes["connection"] = sync_conn
        command.upgrade(config, "head")

    import asyncio

    async def run():
        async with engine.connect() as conn:
            await conn.run_sync(do_upgrade)
        await engine.dispose()

    asyncio.run(run())


def test_fresh_database_migration_creates_all_tables(tmp_path: Path):
    db_file = tmp_path / "fresh_migration.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    _run_upgrade_sync(db_url)

    sync_engine = create_engine(f"sqlite:///{db_file}")
    inspector = inspect(sync_engine)
    table_names = set(inspector.get_table_names())

    expected_tables = {
        "users",
        "admin_drafts",
        "people",
        "surveys",
        "survey_people",
        "votes",
        "admin_users",
        "audit_logs",
        "alembic_version",
    }
    assert expected_tables.issubset(table_names)

    # Check users table columns
    user_columns = {col["name"]: col for col in inspector.get_columns("users")}
    assert "platform" in user_columns
    assert "platform_user_id" in user_columns
    assert "full_name" in user_columns
    assert "is_admin" in user_columns

    sync_engine.dispose()


def test_legacy_database_migration_adoption(tmp_path: Path):
    db_file = tmp_path / "legacy_migration.db"
    sync_url = f"sqlite:///{db_file}"
    async_url = f"sqlite+aiosqlite:///{db_file}"

    # 1. Manually create pre-Alembic schema
    sync_engine = create_engine(sync_url)
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    full_name VARCHAR(200) NOT NULL,
                    username VARCHAR(100),
                    is_admin BOOLEAN NOT NULL,
                    is_active BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX ix_users_telegram_id ON users (telegram_id);"))
        conn.execute(
            text(
                """
                INSERT INTO users (telegram_id, full_name, username, is_admin, is_active, created_at)
                VALUES (987654321, 'کاربر قدیمی', 'old_user', 1, 1, :now);
                """
            ),
            {"now": datetime.now(timezone.utc).isoformat()},
        )
    sync_engine.dispose()

    # 2. Run Alembic upgrade head
    _run_upgrade_sync(async_url)

    # 3. Verify upgraded database
    sync_engine = create_engine(sync_url)
    inspector = inspect(sync_engine)
    table_names = set(inspector.get_table_names())

    # All tables must now exist
    assert "admin_users" in table_names
    assert "audit_logs" in table_names
    assert "people" in table_names
    assert "surveys" in table_names
    assert "votes" in table_names

    # Users table must have platform and platform_user_id
    user_columns = {col["name"] for col in inspector.get_columns("users")}
    assert "platform_user_id" in user_columns
    assert "platform" in user_columns
    assert "telegram_id" not in user_columns

    # Verify existing user data was preserved
    with sync_engine.connect() as conn:
        row = conn.execute(text("SELECT id, platform, platform_user_id, full_name FROM users")).fetchone()
        assert row is not None
        assert row[1] == "telegram"
        assert row[2] == 987654321
        assert row[3] == "کاربر قدیمی"

    # Verify old index was removed
    indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    assert "ix_users_telegram_id" not in indexes

    sync_engine.dispose()


def test_migration_is_idempotent(tmp_path: Path):
    db_file = tmp_path / "idempotent.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # First upgrade
    _run_upgrade_sync(db_url)

    # Second upgrade (must succeed without error)
    _run_upgrade_sync(db_url)

    sync_engine = create_engine(f"sqlite:///{db_file}")
    inspector = inspect(sync_engine)
    assert "users" in inspector.get_table_names()
    assert "admin_users" in inspector.get_table_names()
    sync_engine.dispose()


def test_downgrade_baseline_raises_runtime_error(tmp_path: Path):
    db_file = tmp_path / "downgrade_check.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    _run_upgrade_sync(db_url)

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", db_url)
    engine = create_async_engine(db_url)

    def do_downgrade(sync_conn):
        config.attributes["connection"] = sync_conn
        command.downgrade(config, "base")

    import asyncio

    async def run():
        async with engine.connect() as conn:
            with pytest.raises(RuntimeError, match="Restore a verified backup to roll back"):
                await conn.run_sync(do_downgrade)
        await engine.dispose()

    asyncio.run(run())


def test_metadata_tables_match_migrated_database(tmp_path: Path):
    db_file = tmp_path / "meta_parity.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    _run_upgrade_sync(db_url)

    sync_engine = create_engine(f"sqlite:///{db_file}")
    inspector = inspect(sync_engine)
    db_tables = set(inspector.get_table_names()) - {"alembic_version"}
    meta_tables = set(Base.metadata.tables.keys())

    assert db_tables == meta_tables, f"Difference: {db_tables.symmetric_difference(meta_tables)}"

    for table_name in meta_tables:
        db_cols = {col["name"] for col in inspector.get_columns(table_name)}
        meta_cols = {col.name for col in Base.metadata.tables[table_name].columns}
        assert db_cols == meta_cols, f"Mismatch in {table_name}: db={db_cols}, meta={meta_cols}"

    sync_engine.dispose()


def test_postgresql_migration_alter_column_logic():
    import importlib
    from unittest.mock import MagicMock, patch

    m1 = importlib.import_module("migrations.versions.0001_initial_schema")

    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_inspect = MagicMock()
    mock_inspect.get_table_names.return_value = ["users"]
    mock_inspect.get_columns.return_value = [{"name": "id"}, {"name": "telegram_id"}]
    mock_inspect.get_indexes.return_value = []
    mock_inspect.get_unique_constraints.return_value = []

    with (
        patch.object(m1, "op") as mock_op,
        patch.object(m1, "inspect", return_value=mock_inspect),
    ):
        mock_op.get_bind.return_value = mock_bind
        m1.upgrade()

        # Verify alter_column called with BigInteger and postgresql_using
        calls = [
            c
            for c in mock_op.alter_column.call_args_list
            if c.kwargs.get("postgresql_using") == "platform_user_id::bigint"
        ]
        assert len(calls) == 1

