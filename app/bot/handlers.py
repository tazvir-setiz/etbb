from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards import inline_options, main_menu
from app.exports.excel import build_survey_workbook
from app.config import Settings
from app.models import Person, Survey, SurveyPerson, SurveyStatus, User, Vote
from app.services.voting import VotingError, record_vote, survey_status, survey_statistics

class VoteFlow(StatesGroup):
    comment = State()


def build_router(session_factory: async_sessionmaker, settings: Settings) -> Router:
    router = Router()
    @router.message(CommandStart())
    async def start(message: Message) -> None:
        is_admin = message.from_user.id in settings.admin_ids
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            if user is None:
                session.add(User(telegram_id=message.from_user.id, full_name=message.from_user.full_name,
                                username=message.from_user.username, is_admin=is_admin))
            else:
                user.full_name = message.from_user.full_name
                user.username = message.from_user.username
                user.is_admin = is_admin
            await session.commit()
        await message.answer("سلام! به سامانه ارزیابی خوش آمدید.", reply_markup=main_menu(is_admin))

    @router.message(F.text == "📝 نظرسنجی‌های فعال")
    async def active_surveys(message: Message) -> None:
        async with session_factory() as session:
            surveys = (await session.scalars(select(Survey).where(Survey.status != SurveyStatus.CANCELLED.value))).all()
            available = [survey for survey in surveys if survey_status(survey) == SurveyStatus.ACTIVE]
            if not available:
                await message.answer("در حال حاضر نظرسنجی فعالی وجود ندارد.")
                return
            await message.answer("نظرسنجی موردنظر را انتخاب کنید:", reply_markup=inline_options(
                [(survey.title, f"survey:{survey.id}") for survey in available]
            ))

    @router.callback_query(F.data.startswith("survey:"))
    async def select_survey(callback: CallbackQuery) -> None:
        survey_id = int(callback.data.split(":")[1])
        async with session_factory() as session:
            survey = await session.get(Survey, survey_id)
            if not survey or survey_status(survey) != SurveyStatus.ACTIVE:
                await callback.answer("این نظرسنجی فعال نیست.", show_alert=True)
                return
            people = (await session.scalars(select(Person).join(SurveyPerson).where(
                SurveyPerson.survey_id == survey_id, Person.is_active.is_(True)
            ))).all()
            await callback.message.answer(survey.title, reply_markup=inline_options(
                [(person.display_name, f"person:{survey_id}:{person.id}") for person in people]
            ))
        await callback.answer()

    @router.callback_query(F.data.startswith("person:"))
    async def select_person(callback: CallbackQuery, state: FSMContext) -> None:
        _, survey_id, person_id = callback.data.split(":")
        async with session_factory() as session:
            survey = await session.get(Survey, int(survey_id))
            person = await session.get(Person, int(person_id))
            if not survey or not person or survey_status(survey) != SurveyStatus.ACTIVE:
                await callback.answer("این گزینه دیگر در دسترس نیست.", show_alert=True)
                return
            choices = [("⭐" * score, f"score:{survey_id}:{person_id}:{score}")
                       for score in range(survey.min_score, survey.max_score + 1)]
            await callback.message.answer(f"امتیاز شما به {person.display_name}؟",
                                          reply_markup=inline_options(choices, columns=5))
        await callback.answer()

    @router.callback_query(F.data.startswith("score:"))
    async def select_score(callback: CallbackQuery, state: FSMContext) -> None:
        _, survey_id, person_id, score = callback.data.split(":")
        await state.update_data(survey_id=int(survey_id), person_id=int(person_id), score=int(score))
        async with session_factory() as session:
            survey = await session.get(Survey, int(survey_id))
            if survey and survey.allow_comments:
                await state.set_state(VoteFlow.comment)
                await callback.message.answer("اگر مایلید، نظر خود را بنویسید. برای رد کردن /skip را بفرستید.")
                await callback.answer()
                return
        await save_vote(callback, state, session_factory, None)

    @router.message(VoteFlow.comment)
    async def save_comment(message: Message, state: FSMContext) -> None:
        comment = None if message.text == "/skip" else (message.text or "")[:2000]
        await save_vote(message, state, session_factory, comment)

    @router.message(F.text == "📊 امتیازهای من")
    async def my_votes(message: Message) -> None:
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            if not user:
                await message.answer("هنوز امتیازی ثبت نکرده‌اید.")
                return
            rows = (await session.execute(select(Survey.title, Person.display_name, Vote.score)
                .join(Survey, Survey.id == Vote.survey_id).join(Person, Person.id == Vote.person_id)
                .where(Vote.user_id == user.id).order_by(Vote.created_at.desc()))).all()
            await message.answer("\n".join(f"{title} — {person}: {score}" for title, person, score in rows)
                                 or "هنوز امتیازی ثبت نکرده‌اید.")

    @router.message(F.text == "⚙️ پنل مدیریت")
    async def admin_panel(message: Message) -> None:
        if message.from_user.id not in settings.admin_ids:
            await message.answer("شما دسترسی مدیریت ندارید.")
            return
        await message.answer("فرمان‌های مدیریت:\n/addperson شناسه|نام|نام‌خانوادگی — افزودن فرد\n"
                             "/addsurvey عنوان|شروع ISO|پایان ISO|شناسه افراد با ویرگول — ساخت نظرسنجی\n"
                             "/reports — گزارش‌ها\n/export شناسه — دریافت فایل اکسل")

    @router.message(F.text.startswith("/addperson "))
    async def add_person(message: Message) -> None:
        if message.from_user.id not in settings.admin_ids:
            await message.answer("شما دسترسی مدیریت ندارید.")
            return
        try:
            internal_id, first_name, last_name = [part.strip() for part in message.text[11:].split("|", 2)]
            person = Person(internal_id=internal_id, first_name=first_name, last_name=last_name,
                            display_name=f"{first_name} {last_name}")
            async with session_factory() as session:
                session.add(person)
                await session.commit()
            await message.answer(f"فرد «{person.display_name}» اضافه شد.")
        except (ValueError, IndexError):
            await message.answer("قالب درست: /addperson شناسه|نام|نام‌خانوادگی")

    @router.message(F.text.startswith("/addsurvey "))
    async def add_survey(message: Message) -> None:
        if message.from_user.id not in settings.admin_ids:
            await message.answer("شما دسترسی مدیریت ندارید.")
            return
        try:
            title, start_text, end_text, people_text = [part.strip() for part in message.text[11:].split("|", 3)]
            starts_at = datetime.fromisoformat(start_text)
            ends_at = datetime.fromisoformat(end_text)
            if starts_at.tzinfo is None or ends_at.tzinfo is None or ends_at <= starts_at:
                raise ValueError("timezone or range")
            person_ids = [int(value.strip()) for value in people_text.split(",") if value.strip()]
            async with session_factory() as session:
                survey = Survey(title=title, starts_at=starts_at, ends_at=ends_at,
                                status=SurveyStatus.SCHEDULED.value)
                session.add(survey)
                await session.flush()
                for person_id in person_ids:
                    session.add(SurveyPerson(survey_id=survey.id, person_id=person_id))
                await session.commit()
                survey_id = survey.id
            await message.answer(f"نظرسنجی ساخته شد. شناسه: {survey_id}")
        except (ValueError, IndexError):
            await message.answer("قالب درست: /addsurvey عنوان|شروع ISO دارای منطقه زمانی|پایان ISO|شناسه افراد\n"
                                 "نمونه: /addsurvey ارزیابی|2026-10-08T09:00:00+03:30|2026-10-09T17:00:00+03:30|1,2")

    @router.message(F.text == "/reports")
    async def reports(message: Message) -> None:
        if message.from_user.id not in settings.admin_ids:
            await message.answer("شما دسترسی مدیریت ندارید.")
            return
        async with session_factory() as session:
            surveys = (await session.scalars(select(Survey).order_by(Survey.id.desc()))).all()
            if not surveys:
                await message.answer("هنوز نظرسنجی‌ای ساخته نشده است.")
                return
            await message.answer("گزارش کدام نظرسنجی؟", reply_markup=inline_options(
                [(survey.title, f"report:{survey.id}") for survey in surveys]))

    @router.callback_query(F.data.startswith("report:"))
    async def report(callback: CallbackQuery) -> None:
        if callback.from_user.id not in settings.admin_ids:
            await callback.answer("دسترسی ندارید.", show_alert=True)
            return
        survey_id = int(callback.data.split(":")[1])
        async with session_factory() as session:
            survey = await session.get(Survey, survey_id)
            if not survey:
                await callback.answer("نظرسنجی پیدا نشد.", show_alert=True)
                return
            stats = await survey_statistics(session, survey_id)
            title = survey.title
        summary = "\n".join(f"{item['name']}: {item['votes']} رأی، میانگین {item['average']:.2f}" for item in stats)
        await callback.message.answer(f"گزارش «{title}»\n{summary or 'رأیی ثبت نشده است.'}\n\n/export {survey_id} برای اکسل")
        await callback.answer()

    @router.message(F.text.startswith("/export "))
    async def export(message: Message) -> None:
        if message.from_user.id not in settings.admin_ids:
            await message.answer("شما دسترسی مدیریت ندارید.")
            return
        try:
            survey_id = int(message.text.split(maxsplit=1)[1])
            async with session_factory() as session:
                survey = await session.get(Survey, survey_id)
                if survey is None:
                    await message.answer("نظرسنجی پیدا نشد.")
                    return
                data = await build_survey_workbook(session, survey_id)
                title = survey.title
            from aiogram.types import BufferedInputFile
            safe_name = "".join(char for char in title if char.isalnum() or char in " -_")[:60] or "report"
            await message.answer_document(BufferedInputFile(data.read(), filename=f"{safe_name}.xlsx"))
        except (ValueError, IndexError, TypeError):
            await message.answer("قالب درست: /export شناسه")

    return router


async def save_vote(update: Message | CallbackQuery, state: FSMContext, session_factory, comment: str | None) -> None:
    payload = await state.get_data()
    telegram_id = update.from_user.id
    try:
        async with session_factory() as session:
            await record_vote(session, telegram_id=telegram_id, survey_id=payload["survey_id"],
                              person_id=payload["person_id"], score=payload["score"], comment=comment)
        response = "امتیاز شما با موفقیت ثبت شد."
    except VotingError as exc:
        response = str(exc)
    await state.clear()
    if isinstance(update, CallbackQuery):
        await update.message.answer(response)
        await update.answer()
    else:
        await update.answer(response)
