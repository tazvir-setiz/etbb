from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Person, Survey, SurveyPerson, SurveyStatus, User, Vote


class VotingError(Exception):
    """A user-facing voting rule was not satisfied."""


def survey_status(survey: Survey, now: datetime | None = None) -> SurveyStatus:
    current = now or datetime.now(timezone.utc)
    start, end = survey.starts_at, survey.ends_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if survey.status == SurveyStatus.CANCELLED:
        return SurveyStatus.CANCELLED
    if current < start:
        return SurveyStatus.SCHEDULED
    if current > end:
        return SurveyStatus.FINISHED
    return SurveyStatus.ACTIVE


async def record_vote(
    session: AsyncSession,
    *,
    telegram_id: int,
    survey_id: int,
    person_id: int,
    score: int,
    comment: str | None = None,
    now: datetime | None = None,
) -> Vote:
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise VotingError("نظرسنجی پیدا نشد.")
    if survey_status(survey, now) != SurveyStatus.ACTIVE:
        raise VotingError("این نظرسنجی در حال حاضر فعال نیست.")
    if not survey.min_score <= score <= survey.max_score:
        raise VotingError(f"امتیاز باید بین {survey.min_score} و {survey.max_score} باشد.")
    membership = await session.scalar(
        select(SurveyPerson.id).where(
            SurveyPerson.survey_id == survey_id, SurveyPerson.person_id == person_id
        )
    )
    if membership is None:
        raise VotingError("این فرد در نظرسنجی انتخاب نشده است.")
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(telegram_id=telegram_id, full_name="کاربر")
        session.add(user)
        await session.flush()
    existing = await session.scalar(
        select(Vote).where(
            Vote.survey_id == survey_id, Vote.person_id == person_id, Vote.user_id == user.id
        )
    )
    if existing:
        if not survey.allow_vote_editing:
            raise VotingError("شما قبلاً به این فرد امتیاز داده‌اید.")
        existing.score = score
        existing.comment = comment
        existing.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(existing)
        return existing
    vote = Vote(
        survey_id=survey_id,
        person_id=person_id,
        user_id=user.id,
        score=score,
        comment=comment if survey.allow_comments else None,
    )
    session.add(vote)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise VotingError("شما قبلاً ثبت کرده‌اید؛ امکان ثبت دوباره وجود ندارد.") from exc
    await session.refresh(vote)
    return vote


async def survey_statistics(session: AsyncSession, survey_id: int) -> list[dict[str, object]]:
    rows = await session.execute(
        select(Person.id, Person.display_name, func.count(Vote.id), func.avg(Vote.score))
        .join(SurveyPerson, SurveyPerson.person_id == Person.id)
        .outerjoin(Vote, (Vote.person_id == Person.id) & (Vote.survey_id == survey_id))
        .where(SurveyPerson.survey_id == survey_id)
        .group_by(Person.id, Person.display_name)
        .order_by(Person.display_name)
    )
    return [
        {"person_id": person_id, "name": name, "votes": count, "average": float(avg or 0)}
        for person_id, name, count, avg in rows
    ]
