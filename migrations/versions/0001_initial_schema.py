"""Adopt the pre-Alembic schema and create missing tables.

Revision ID: 0001_initial_schema
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _create_missing_tables() -> None:
    names = set(inspect(op.get_bind()).get_table_names())
    if "users" not in names:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("platform", sa.String(16), nullable=False),
            sa.Column("platform_user_id", sa.BigInteger(), nullable=False),
            sa.Column("full_name", sa.String(200), nullable=False),
            sa.Column("username", sa.String(100)),
            sa.Column("is_admin", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "platform", "platform_user_id", name="uq_user_platform_platform_user_id"
            ),
        )
        names.add("users")
    if "admin_drafts" not in names:
        op.create_table(
            "admin_drafts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("platform", sa.String(16), nullable=False),
            sa.Column("platform_user_id", sa.BigInteger(), nullable=False),
            sa.Column("draft_type", sa.String(32), nullable=False),
            sa.Column("step", sa.String(128), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "platform", "platform_user_id", name="uq_admin_draft_platform_user"
            ),
        )
        names.add("admin_drafts")
    if "people" not in names:
        op.create_table(
            "people",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("first_name", sa.String(100), nullable=False),
            sa.Column("last_name", sa.String(100), nullable=False),
            sa.Column("display_name", sa.String(201), nullable=False),
            sa.Column("internal_id", sa.String(64), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("is_active", sa.Boolean(), nullable=False),
        )
        names.add("people")
    if "surveys" not in names:
        op.create_table(
            "surveys",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("min_score", sa.Integer(), nullable=False),
            sa.Column("max_score", sa.Integer(), nullable=False),
            sa.Column("allow_comments", sa.Boolean(), nullable=False),
            sa.Column("allow_vote_editing", sa.Boolean(), nullable=False),
            sa.Column("anonymous", sa.Boolean(), nullable=False),
            sa.CheckConstraint("min_score < max_score", name="ck_survey_score_range"),
        )
        names.add("surveys")
    if "survey_people" not in names:
        op.create_table(
            "survey_people",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("survey_id", sa.Integer(), sa.ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
            sa.Column("person_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="RESTRICT"), nullable=False),
            sa.UniqueConstraint("survey_id", "person_id", name="uq_survey_person"),
        )
        names.add("survey_people")
    if "votes" not in names:
        op.create_table(
            "votes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("survey_id", sa.Integer(), sa.ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
            sa.Column("person_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("survey_id", "person_id", "user_id", name="uq_vote_survey_person_user"),
            sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_vote_score"),
        )


def _ensure_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    inspector = inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    constraints = {item.get("name") for item in inspector.get_unique_constraints(table)}
    if name not in indexes | constraints:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    if "users" in inspect(bind).get_table_names():
        columns = {column["name"] for column in inspect(bind).get_columns("users")}
        if "platform" not in columns:
            op.add_column(
                "users",
                sa.Column("platform", sa.String(16), nullable=False, server_default="telegram"),
            )
        if "telegram_id" in columns and "platform_user_id" not in columns:
            op.alter_column("users", "telegram_id", new_column_name="platform_user_id")
        if bind.dialect.name == "postgresql":
            op.alter_column("users", "platform_user_id", type_=sa.BigInteger())
        bind.execute(text("DROP INDEX IF EXISTS ix_users_telegram_id"))

    _create_missing_tables()
    _ensure_index("uq_user_platform_platform_user_id", "users", ["platform", "platform_user_id"], unique=True)
    _ensure_index("ix_users_platform", "users", ["platform"])
    _ensure_index("ix_users_platform_user_id", "users", ["platform_user_id"])
    _ensure_index("ix_people_display_name", "people", ["display_name"])
    _ensure_index("ix_people_internal_id", "people", ["internal_id"], unique=True)
    _ensure_index("ix_surveys_starts_at", "surveys", ["starts_at"])
    _ensure_index("ix_surveys_ends_at", "surveys", ["ends_at"])
    for table, column in (
        ("survey_people", "survey_id"),
        ("survey_people", "person_id"),
        ("votes", "survey_id"),
        ("votes", "person_id"),
        ("votes", "user_id"),
    ):
        _ensure_index(f"ix_{table}_{column}", table, [column])
    _ensure_index("ix_vote_survey_person", "votes", ["survey_id", "person_id"])


def downgrade() -> None:
    raise RuntimeError(
        "This baseline may adopt a database with user data. Restore a verified backup to roll back."
    )
