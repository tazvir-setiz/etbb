from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SurveyStatus(StrEnum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_user_platform_platform_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), default="telegram", index=True)
    platform_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    votes: Mapped[list["Vote"]] = relationship(back_populates="user")


class AdminDraft(Base):
    __tablename__ = "admin_drafts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_admin_draft_platform_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(16))
    platform_user_id: Mapped[int] = mapped_column(BigInteger)
    draft_type: Mapped[str] = mapped_column(String(32))
    step: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(201), index=True)
    internal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Survey(Base):
    __tablename__ = "surveys"
    __table_args__ = (CheckConstraint("min_score < max_score", name="ck_survey_score_range"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default=SurveyStatus.DRAFT.value)
    min_score: Mapped[int] = mapped_column(Integer, default=1)
    max_score: Mapped[int] = mapped_column(Integer, default=5)
    allow_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_vote_editing: Mapped[bool] = mapped_column(Boolean, default=True)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=True)
    people: Mapped[list["SurveyPerson"]] = relationship(back_populates="survey", cascade="all, delete-orphan")
    votes: Mapped[list["Vote"]] = relationship(back_populates="survey", cascade="all, delete-orphan")


class SurveyPerson(Base):
    __tablename__ = "survey_people"
    __table_args__ = (UniqueConstraint("survey_id", "person_id", name="uq_survey_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    survey: Mapped[Survey] = relationship(back_populates="people")
    person: Mapped[Person] = relationship()


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("survey_id", "person_id", "user_id", name="uq_vote_survey_person_user"),
        CheckConstraint("score >= 1 AND score <= 5", name="ck_vote_score"),
        Index("ix_vote_survey_person", "survey_id", "person_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="votes")
    survey: Mapped[Survey] = relationship(back_populates="votes")
