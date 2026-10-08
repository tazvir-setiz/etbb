"""Adopt existing installations and create the current schema where missing.

Revision ID: 0001_initial_schema
Revises:
"""
from alembic import op
from sqlalchemy import BigInteger, Column, String, inspect, text

from app.models import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "platform" not in columns:
            op.add_column(
                "users",
                Column("platform", String(16), nullable=False, server_default="telegram"),
            )
        if "telegram_id" in columns and "platform_user_id" not in columns:
            op.alter_column("users", "telegram_id", new_column_name="platform_user_id")
        if bind.dialect.name == "postgresql":
            op.alter_column("users", "platform_user_id", type_=BigInteger())
        bind.execute(text("DROP INDEX IF EXISTS ix_users_telegram_id"))
        inspector = inspect(bind)
        index_names = {index["name"] for index in inspector.get_indexes("users")}
        constraint_names = {item.get("name") for item in inspector.get_unique_constraints("users")}
        if "uq_user_platform_platform_user_id" not in index_names | constraint_names:
            op.create_index(
                "uq_user_platform_platform_user_id",
                "users",
                ["platform", "platform_user_id"],
                unique=True,
            )
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    raise RuntimeError(
        "This baseline may adopt a database with user data. Restore a verified backup to roll back."
    )
