import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards import inline_options, participant_menu
from app.config import Settings
from app.models import AdminRole, Person, Survey, SurveyPerson, SurveyStatus, User, Vote
from app.services.admin_roles import get_user_role
from app.services.users import register_or_update_user
from app.services.voting import VotingError, record_vote, survey_status

logger = logging.getLogger(__name__)


class VoteFlow(StatesGroup):
    comment = State()


def build_user_router(session_factory: async_sessionmaker, settings: Settings) -> Router:
    router = Router(name="user")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        async with session_factory() as session:
            role = await get_user_role(
                session,
                platform=settings.bot_platform,
                platform_user_id=message.from_user.id,
                initial_admin_ids=settings.admin_ids,
            )
            is_admin = role is not None
            is_owner = role == AdminRole.OWNER
            await register_or_update_user(
                session,
                platform=settings.bot_platform,
                platform_user_id=message.from_user.id,
                full_name=message.from_user.full_name,
                username=message.from_user.username,
                is_admin=is_admin,
            )
        logger.info(
            "[%s] /start processed for user %s (%s, username=@%s). Role=%s (is_admin=%s, is_owner=%s)",
            settings.bot_platform,
            message.from_user.id,
            message.from_user.full_name,
            message.from_user.username,
            role.value if role else "EVALUATOR",
            is_admin,
            is_owner,
        )
        if is_admin:
            from app.bot.keyboards import admin_menu

            greeting = "سلام مالک گرامی!" if is_owner else "سلام مدیر گرامی!"
            await message.answer(f"{greeting} از پنل مدیریت یک بخش را انتخاب کنید.", reply_markup=admin_menu(is_owner=is_owner))
        else:
            await message.answer(
                "سلام! به سامانه ارزیابی خوش آمدید.", reply_markup=participant_menu()
            )

    @router.message(F.text == "📝 نظرسنجی‌های فعال")
    async def active_surveys(message: Message) -> None:
        async with session_factory() as session:
            surveys = (
                await session.scalars(
                    select(Survey).where(Survey.status != SurveyStatus.CANCELLED.value)
                )
            ).all()
            available = [survey for survey in surveys if survey_status(survey) == SurveyStatus.ACTIVE]
            logger.info(
                "[%s] User %s requested active surveys. Found %d active out of %d total surveys.",
                settings.bot_platform,
                message.from_user.id,
                len(available),
                len(surveys),
            )
            if not available:
                await message.answer("در حال حاضر نظرسنجی فعالی وجود ندارد.")
                return
            await message.answer(
                "نظرسنجی موردنظر را انتخاب کنید:",
                reply_markup=inline_options(
                    [(survey.title, f"survey:{survey.id}") for survey in available]
                ),
            )

    @router.callback_query(F.data.startswith("survey:"))
    async def select_survey(callback: CallbackQuery) -> None:
        survey_id = int(callback.data.split(":")[1])
        async with session_factory() as session:
            survey = await session.get(Survey, survey_id)
            if not survey or survey_status(survey) != SurveyStatus.ACTIVE:
                logger.warning(
                    "[%s] User %s clicked inactive or missing survey id=%d",
                    settings.bot_platform,
                    callback.from_user.id,
                    survey_id,
                )
                await callback.answer("این نظرسنجی فعال نیست.", show_alert=True)
                return
            people = (
                await session.scalars(
                    select(Person)
                    .join(SurveyPerson)
                    .where(
                        SurveyPerson.survey_id == survey_id,
                        Person.is_active.is_(True),
                    )
                    .order_by(Person.display_name)
                )
            ).all()
            logger.info(
                "[%s] User %s opened survey id=%d ('%s'). Found %d active people to rate.",
                settings.bot_platform,
                callback.from_user.id,
                survey_id,
                survey.title,
                len(people),
            )
            if not people:
                await callback.message.answer("برای این نظرسنجی فرد فعالی ثبت نشده است.")
            else:
                await callback.message.answer(
                    survey.title,
                    reply_markup=inline_options(
                        [(person.display_name, f"person:{survey_id}:{person.id}") for person in people]
                    ),
                )
        await callback.answer()

    @router.callback_query(F.data.startswith("person:"))
    async def select_person(callback: CallbackQuery) -> None:
        _, survey_id, person_id = callback.data.split(":")
        async with session_factory() as session:
            survey = await session.get(Survey, int(survey_id))
            person = await session.get(Person, int(person_id))
            if not survey or not person or survey_status(survey) != SurveyStatus.ACTIVE:
                logger.warning(
                    "[%s] User %s attempted to rate unavailable person id=%s in survey id=%s",
                    settings.bot_platform,
                    callback.from_user.id,
                    person_id,
                    survey_id,
                )
                await callback.answer("این گزینه دیگر در دسترس نیست.", show_alert=True)
                return
            logger.info(
                "[%s] User %s selected person id=%s ('%s') in survey id=%s ('%s')",
                settings.bot_platform,
                callback.from_user.id,
                person_id,
                person.display_name,
                survey_id,
                survey.title,
            )
            choices = [
                ("⭐" * score, f"score:{survey_id}:{person_id}:{score}")
                for score in range(survey.min_score, survey.max_score + 1)
            ]
            await callback.message.answer(
                f"امتیاز شما به {person.display_name}؟",
                reply_markup=inline_options(choices, columns=5),
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("score:"))
    async def select_score(callback: CallbackQuery, state: FSMContext) -> None:
        _, survey_id, person_id, score = callback.data.split(":")
        await state.update_data(survey_id=int(survey_id), person_id=int(person_id), score=int(score))
        logger.info(
            "[%s] User %s chose score=%s for person id=%s in survey id=%s",
            settings.bot_platform,
            callback.from_user.id,
            score,
            person_id,
            survey_id,
        )
        async with session_factory() as session:
            survey = await session.get(Survey, int(survey_id))
            if survey and survey.allow_comments:
                await state.set_state(VoteFlow.comment)
                logger.info(
                    "[%s] Survey id=%s allows comments; prompting user %s for comment.",
                    settings.bot_platform,
                    survey_id,
                    callback.from_user.id,
                )
                await callback.message.answer(
                    "اگر مایلید، نظر خود را بنویسید. برای رد کردن /skip را بفرستید."
                )
                await callback.answer()
                return
        await save_vote(callback, state, session_factory, settings.bot_platform, None)

    @router.message(VoteFlow.comment)
    async def save_comment(message: Message, state: FSMContext) -> None:
        comment = None if message.text == "/skip" else (message.text or "")[:2000]
        logger.info(
            "[%s] User %s provided comment (length=%d, skipped=%s)",
            settings.bot_platform,
            message.from_user.id,
            len(comment) if comment else 0,
            comment is None,
        )
        await save_vote(message, state, session_factory, settings.bot_platform, comment)

    @router.message(F.text == "📊 امتیازهای من")
    async def my_votes(message: Message) -> None:
        async with session_factory() as session:
            user = await session.scalar(
                select(User).where(
                    User.platform == settings.bot_platform,
                    User.platform_user_id == message.from_user.id,
                )
            )
            if not user:
                logger.info(
                    "[%s] User %s checked 'my votes' but user record not found.",
                    settings.bot_platform,
                    message.from_user.id,
                )
                await message.answer("هنوز امتیازی ثبت نکرده‌اید.")
                return
            rows = (
                await session.execute(
                    select(Survey.title, Person.display_name, Vote.score)
                    .join(Survey, Survey.id == Vote.survey_id)
                    .join(Person, Person.id == Vote.person_id)
                    .where(Vote.user_id == user.id)
                    .order_by(Vote.created_at.desc())
                )
            ).all()
            logger.info(
                "[%s] User %s viewed 'my votes'; found %d registered vote(s).",
                settings.bot_platform,
                message.from_user.id,
                len(rows),
            )
            await message.answer(
                "\n".join(f"{title} — {person}: {score}" for title, person, score in rows)
                or "هنوز امتیازی ثبت نکرده‌اید."
            )

    @router.message(F.text == "ℹ️ راهنما")
    async def help_message(message: Message) -> None:
        await message.answer(
            "از «نظرسنجی‌های فعال» یک نظرسنجی را انتخاب کنید، سپس به افراد امتیاز بدهید. "
            "برای دیدن امتیازهای ثبت‌شدهٔ خود، «امتیازهای من» را بزنید."
        )

    return router


async def save_vote(
    update: Message | CallbackQuery,
    state: FSMContext,
    session_factory: async_sessionmaker,
    platform: str,
    comment: str | None,
) -> None:
    payload = await state.get_data()
    user_id = update.from_user.id
    try:
        async with session_factory() as session:
            vote = await record_vote(
                session,
                platform=platform,
                platform_user_id=user_id,
                survey_id=payload["survey_id"],
                person_id=payload["person_id"],
                score=payload["score"],
                comment=comment,
            )
        logger.info(
            "[%s] Vote successfully persisted for user %s: vote_id=%s, survey_id=%s, person_id=%s, score=%s",
            platform,
            user_id,
            vote.id,
            payload["survey_id"],
            payload["person_id"],
            payload["score"],
        )
        response = "امتیاز شما با موفقیت ثبت شد."
    except VotingError as exc:
        logger.warning(
            "[%s] Vote rejected for user %s on survey_id=%s, person_id=%s: %s",
            platform,
            user_id,
            payload.get("survey_id"),
            payload.get("person_id"),
            exc,
        )
        response = str(exc)
    await state.clear()
    if isinstance(update, CallbackQuery):
        await update.message.answer(response)
        await update.answer()
    else:
        await update.answer(response)
