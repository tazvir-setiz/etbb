from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Person, Survey, SurveyPerson, SurveyStatus
from app.services.voting import VotingError, record_vote, survey_status


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def setup_survey(factory, start_offset=-1, end_offset=1, editing=True):
    async with factory() as session:
        now = datetime.now(timezone.utc)
        person = Person(first_name="علی", last_name="رضایی", display_name="علی رضایی", internal_id="P-1")
        survey = Survey(title="ارزیابی", starts_at=now + timedelta(hours=start_offset),
                        ends_at=now + timedelta(hours=end_offset), status=SurveyStatus.ACTIVE.value,
                        allow_vote_editing=editing)
        session.add_all([person, survey])
        await session.flush()
        session.add(SurveyPerson(survey_id=survey.id, person_id=person.id))
        await session.commit()
        return survey.id, person.id, now


@pytest.mark.asyncio
async def test_vote_record_and_duplicate_edit(session_factory):
    survey_id, person_id, now = await setup_survey(session_factory)
    async with session_factory() as session:
        first = await record_vote(session, telegram_id=42, survey_id=survey_id,
                                  person_id=person_id, score=3, now=now)
    assert first.score == 3
    async with session_factory() as session:
        second = await record_vote(session, telegram_id=42, survey_id=survey_id,
                                   person_id=person_id, score=5, now=now)
    assert second.id == first.id
    assert second.score == 5


@pytest.mark.asyncio
async def test_vote_rejected_outside_window(session_factory):
    survey_id, person_id, now = await setup_survey(session_factory, start_offset=1, end_offset=2)
    async with session_factory() as session:
        with pytest.raises(VotingError, match="فعال نیست"):
            await record_vote(session, telegram_id=42, survey_id=survey_id,
                              person_id=person_id, score=3, now=now)


@pytest.mark.asyncio
async def test_status_transitions(session_factory):
    survey_id, _, now = await setup_survey(session_factory, start_offset=1, end_offset=2)
    async with session_factory() as session:
        survey = await session.get(Survey, survey_id)
        assert survey_status(survey, now) == SurveyStatus.SCHEDULED
        assert survey_status(survey, now + timedelta(hours=3)) == SurveyStatus.FINISHED
