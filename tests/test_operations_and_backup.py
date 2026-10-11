import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import check_system, main
from app.models import Base, Person, Survey, SurveyPerson, SurveyStatus, User, Vote


@pytest.mark.asyncio
async def test_system_check_success():
    with patch("app.main.initialize_database") as mock_init:
        mock_init.return_value = None
        result = await check_system()
        assert result is True


@pytest.mark.asyncio
async def test_system_check_failure():
    with patch("app.main.initialize_database", side_effect=Exception("DB Connection failed")):
        result = await check_system()
        assert result is False


@pytest.mark.asyncio
async def test_empty_bot_token_raises_runtime_error():
    with patch("app.main.get_settings") as mock_settings:
        mock_settings.return_value.bot_token = ""
        with pytest.raises(RuntimeError, match="BOT_TOKEN is empty"):
            await main()


@pytest.mark.asyncio
async def test_sqlite_backup_and_restore_cycle(tmp_path: Path):
    db_file = tmp_path / "live_survey.db"
    backup_file = tmp_path / "backup_survey.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # 1. Initialize DB and create schema
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # 2. Seed initial data
    now = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
    async with factory() as session:
        user = User(platform="telegram", platform_user_id=1001, full_name="رأی‌دهنده اصلی")
        person = Person(first_name="علیرضا", last_name="کریمی", display_name="علیرضا کریمی", internal_id="OP-1")
        survey = Survey(
            title="نظرسنجی پشتیبان‌گیری",
            starts_at=now,
            ends_at=now,
            status=SurveyStatus.ACTIVE.value,
        )
        session.add_all([user, person, survey])
        await session.flush()
        sp = SurveyPerson(survey_id=survey.id, person_id=person.id)
        vote = Vote(survey_id=survey.id, person_id=person.id, user_id=user.id, score=5, comment="بسیار عالی")
        session.add_all([sp, vote])
        await session.commit()
    await engine.dispose()

    # 3. Simulate taking a verified SQLite backup
    shutil.copy2(db_file, backup_file)
    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    # 4. Simulate accidental corruption / data loss on live DB
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        # Delete all votes and survey persons
        votes = (await session.execute(select(Vote))).scalars().all()
        for v in votes:
            await session.delete(v)
        await session.commit()
        # Verify it is deleted
        remaining_votes = (await session.execute(select(Vote))).scalars().all()
        assert len(remaining_votes) == 0
    await engine.dispose()

    # 5. Restore from backup
    shutil.copy2(backup_file, db_file)

    # 6. Verify restored database has all original data intact
    engine_restored = create_async_engine(db_url)
    factory_restored = async_sessionmaker(engine_restored, expire_on_commit=False)
    async with factory_restored() as session:
        restored_votes = (await session.execute(select(Vote))).scalars().all()
        assert len(restored_votes) == 1
        assert restored_votes[0].score == 5
        assert restored_votes[0].comment == "بسیار عالی"

        restored_person = (await session.execute(select(Person).where(Person.internal_id == "OP-1"))).scalar_one()
        assert restored_person.display_name == "علیرضا کریمی"
    await engine_restored.dispose()


@pytest.mark.asyncio
async def test_volume_persistence_across_engine_restarts(tmp_path: Path):
    # Simulate /data volume mount in container
    volume_dir = tmp_path / "data"
    volume_dir.mkdir(parents=True, exist_ok=True)
    db_path = volume_dir / "survey_bot.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # First session: create schema and add person
    engine1 = create_async_engine(db_url)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory1 = async_sessionmaker(engine1, expire_on_commit=False)
    async with factory1() as session:
        session.add(Person(first_name="سارا", last_name="راد", display_name="سارا راد", internal_id="VOL-1"))
        await session.commit()
    await engine1.dispose()

    # Second session: simulate container restart, reconnect to same persistent volume path
    engine2 = create_async_engine(db_url)
    factory2 = async_sessionmaker(engine2, expire_on_commit=False)
    async with factory2() as session:
        person = (await session.execute(select(Person).where(Person.internal_id == "VOL-1"))).scalar_one_or_none()
        assert person is not None
        assert person.display_name == "سارا راد"
    await engine2.dispose()
