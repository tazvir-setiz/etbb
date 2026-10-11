"""Add admin roles and audit logs tables.

Revision ID: 0002_admin_roles_and_audit_logs
Revises: 0001_initial_schema
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_admin_roles_and_audit_logs"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _ensure_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    inspector = inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    constraints = {item.get("name") for item in inspector.get_unique_constraints(table)}
    if name not in indexes | constraints:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    names = set(inspect(op.get_bind()).get_table_names())
    if "admin_users" not in names:
        op.create_table(
            "admin_users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("platform", sa.String(16), nullable=False),
            sa.Column("platform_user_id", sa.BigInteger(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="ADMIN"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "platform", "platform_user_id", name="uq_admin_user_platform_platform_user_id"
            ),
        )
    if "audit_logs" not in names:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("platform", sa.String(16), nullable=False),
            sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("target_type", sa.String(32), nullable=False),
            sa.Column("target_id", sa.String(64), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    _ensure_index(
        "uq_admin_user_platform_platform_user_id",
        "admin_users",
        ["platform", "platform_user_id"],
        unique=True,
    )
    _ensure_index("ix_admin_users_platform", "admin_users", ["platform"])
    _ensure_index("ix_admin_users_platform_user_id", "admin_users", ["platform_user_id"])
    _ensure_index("ix_audit_logs_platform", "audit_logs", ["platform"])
    _ensure_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    _ensure_index("ix_audit_logs_action", "audit_logs", ["action"])
    _ensure_index("ix_audit_logs_target_type", "audit_logs", ["target_type"])
    _ensure_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    names = set(inspect(op.get_bind()).get_table_names())
    if "audit_logs" in names:
        op.drop_table("audit_logs")
    if "admin_users" in names:
        op.drop_table("admin_users")
