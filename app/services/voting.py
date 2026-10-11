import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Person, Survey, SurveyPerson, SurveyStatus, User, Vote

logger = logging.getLogger(__name__)


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
    platform: str,
    platform_user_id: int,
    survey_id: int,
    person_id: int,
    score: int,
    comment: str | None = None,
    now: datetime | None = None,
) -> Vote:
    logger.info(
        "[%s] Attempting to record vote: user_id=%s, survey_id=%s, person_id=%s, score=%s (has_comment=%s)",
        platform,
        platform_user_id,
        survey_id,
        person_id,
        score,
        bool(comment),
    )
    survey = await session.get(Survey, survey_id)
    if survey is None:
        logger.warning("[%s] Vote rejected: survey id=%s not found", platform, survey_id)
        raise VotingError("نظرسنجی پیدا نشد.")
    st = survey_status(survey, now)
    if st != SurveyStatus.ACTIVE:
        logger.warning(
            "[%s] Vote rejected: survey id=%s is not active (current status=%s)",
            platform,
            survey_id,
            st.value,
        )
        raise VotingError("این نظرسنجی در حال حاضر فعال نیست.")
    if not survey.min_score <= score <= survey.max_score:
        logger.warning(
            "[%s] Vote rejected: score=%s out of allowed range [%s, %s] for survey id=%s",
            platform,
            score,
            survey.min_score,
            survey.max_score,
            survey_id,
        )
        raise VotingError(f"امتیاز باید بین {survey.min_score} و {survey.max_score} باشد.")
    membership = await session.scalar(
        select(SurveyPerson.id).where(
            SurveyPerson.survey_id == survey_id, SurveyPerson.person_id == person_id
        )
    )
    if membership is None:
        logger.warning(
            "[%s] Vote rejected: person id=%s is not a member of survey id=%s",
            platform,
            person_id,
            survey_id,
        )
        raise VotingError("این فرد در نظرسنجی انتخاب نشده است.")
    user = await session.scalar(
        select(User).where(User.platform == platform, User.platform_user_id == platform_user_id)
    )
    if user is None:
        user = User(platform=platform, platform_user_id=platform_user_id, full_name="کاربر")
        session.add(user)
        await session.flush()
        logger.info("[%s] Auto-created user record for platform_user_id=%s", platform, platform_user_id)
    existing = await session.scalar(
        select(Vote).where(
            Vote.survey_id == survey_id, Vote.person_id == person_id, Vote.user_id == user.id
        )
    )
    if existing:
        if not survey.allow_vote_editing:
            logger.warning(
                "[%s] Vote edit rejected: user id=%s already voted on person id=%s in survey id=%s (editing disabled)",
                platform,
                platform_user_id,
                person_id,
                survey_id,
            )
            raise VotingError("شما قبلاً به این فرد امتیاز داده‌اید.")
        old_score = existing.score
        existing.score = score
        existing.comment = comment if survey.allow_comments else None
        existing.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(existing)
        logger.info(
            "[%s] Vote id=%s updated for user %s: score changed from %s to %s",
            platform,
            existing.id,
            platform_user_id,
            old_score,
            score,
        )
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
        logger.warning(
            "[%s] Vote insert IntegrityError for user %s (survey=%s, person=%s): duplicate detected",
            platform,
            platform_user_id,
            survey_id,
            person_id,
        )
        raise VotingError("شما قبلاً ثبت کرده‌اید؛ امکان ثبت دوباره وجود ندارد.") from exc
    await session.refresh(vote)
    logger.info(
        "[%s] New vote id=%s recorded successfully for user %s (survey=%s, person=%s, score=%s)",
        platform,
        vote.id,
        platform_user_id,
        survey_id,
        person_id,
        score,
    )
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
    stats = [
        {"person_id": person_id, "name": name, "votes": count, "average": float(avg or 0)}
        for person_id, name, count, avg in rows
    ]
    logger.debug("survey_statistics calculated for survey id=%s: %d participants evaluated", survey_id, len(stats))
    return stats
