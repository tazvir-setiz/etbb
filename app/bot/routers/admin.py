from datetime import datetime, timezone
from math import ceil
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.dispatcher.event.bases import SkipHandler
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards import admin_menu, inline_options, paginated_options, participant_menu
from app.config import Settings
from app.exports.excel import build_survey_workbook
from app.models import AdminDraft, Person, Survey, SurveyPerson, SurveyStatus, Vote
from app.services.admin_drafts import delete_admin_draft, get_admin_draft, save_admin_draft
from app.services.people_import import PeopleImportError, parse_people_file
from app.services.users import register_or_update_user
from app.services.voting import survey_statistics, survey_status

PAGE_SIZE = 8


class PersonWizard(StatesGroup):
    internal_id = State()
    first_name = State()
    last_name = State()
    description = State()
    search = State()


class PersonEditFlow(StatesGroup):
    value = State()


class PersonBulkFlow(StatesGroup):
    confirm = State()


class SurveyWizard(StatesGroup):
    title = State()
    starts_at = State()
    ends_at = State()
    description = State()
    people = State()


class SurveyEditFlow(StatesGroup):
    title = State()
    description = State()
    starts_at = State()
    ends_at = State()
    people = State()


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


async def _persist_draft(
    session_factory: async_sessionmaker,
    settings: Settings,
    user_id: int,
    state: FSMContext,
    draft_type: str,
) -> None:
    step = await state.get_state()
    if step is None:
        return
    await save_admin_draft(
        session_factory,
        platform=settings.bot_platform,
        platform_user_id=user_id,
        draft_type=draft_type,
        step=step,
        payload=await state.get_data(),
    )


async def _delete_draft(
    session_factory: async_sessionmaker,
    settings: Settings,
    user_id: int,
) -> None:
    await delete_admin_draft(
        session_factory,
        platform=settings.bot_platform,
        platform_user_id=user_id,
    )


def _digits_to_ascii(value: str) -> str:
    return value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def _parse_datetime(value: str, timezone_name: str) -> datetime:
    parsed = datetime.fromisoformat(_digits_to_ascii(value.strip()))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def _as_utc_if_naive(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _status_label(survey: Survey) -> str:
    labels = {
        SurveyStatus.DRAFT: "پیش‌نویس",
        SurveyStatus.SCHEDULED: "زمان‌بندی‌شده",
        SurveyStatus.ACTIVE: "فعال",
        SurveyStatus.FINISHED: "پایان‌یافته",
        SurveyStatus.CANCELLED: "لغوشده",
    }
    return labels[survey_status(survey)]


def _short_label(value: str, limit: int = 58) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _with_footer(
    keyboard: InlineKeyboardMarkup,
    *buttons: tuple[str, str],
) -> InlineKeyboardMarkup:
    rows = [*keyboard.inline_keyboard]
    rows.extend([[InlineKeyboardButton(text=label, callback_data=data)] for label, data in buttons])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_or_edit(target: Message | CallbackQuery, text: str, reply_markup=None) -> None:
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=reply_markup)
    else:
        await target.answer(text, reply_markup=reply_markup)


async def _render_people(
    target: Message | CallbackQuery,
    session_factory: async_sessionmaker,
    *,
    page: int = 0,
    query: str = "",
) -> None:
    filters = []
    if query:
        filters.append(Person.display_name.ilike(f"%{query}%"))
        filters.append(Person.internal_id.ilike(f"%{query}%"))
    statement = select(Person)
    count_statement = select(func.count(Person.id))
    if filters:
        from sqlalchemy import or_

        condition = or_(*filters)
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    async with session_factory() as session:
        total = await session.scalar(count_statement) or 0
        page_count = max(1, ceil(total / PAGE_SIZE))
        page = min(max(page, 0), page_count - 1)
        people = (
            await session.scalars(
                statement.order_by(Person.display_name).offset(page * PAGE_SIZE).limit(PAGE_SIZE)
            )
        ).all()
    description = f" افراد ({total})"
    if query:
        description += f" برای «{query}»"
    lines = [f"مدیریت{description} را انتخاب کنید:", ""]
    if not people:
        lines.append("فردی پیدا نشد.")
    items = [
        (
            _short_label(
                f"{'🟢' if person.is_active else '⚪'} {person.display_name} · {person.internal_id}"
            ),
            f"adm:person:{person.id}",
        )
        for person in people
    ]
    keyboard = paginated_options(items, page=page, page_count=page_count, prefix="adm:people:page")
    keyboard = _with_footer(
        keyboard,
        ("➕ افزودن فرد", "adm:people:add"),
        ("📤 ورود گروهی از فایل", "adm:people:import:start"),
        ("🔎 جست‌وجو", "adm:people:search"),
        ("↩️ پنل مدیریت", "adm:home"),
    )
    await _send_or_edit(target, "\n".join(lines), keyboard)


async def _render_surveys(
    target: Message | CallbackQuery,
    session_factory: async_sessionmaker,
    *,
    page: int = 0,
) -> None:
    async with session_factory() as session:
        total = await session.scalar(select(func.count(Survey.id))) or 0
        page_count = max(1, ceil(total / PAGE_SIZE))
        page = min(max(page, 0), page_count - 1)
        surveys = (
            await session.scalars(
                select(Survey).order_by(Survey.id.desc()).offset(page * PAGE_SIZE).limit(PAGE_SIZE)
            )
        ).all()
        rows = [
            (_short_label(f"{_status_label(survey)} · {survey.title}"), f"adm:survey:{survey.id}")
            for survey in surveys
        ]
    keyboard = paginated_options(rows, page=page, page_count=page_count, prefix="adm:surveys:page")
    keyboard = _with_footer(
        keyboard,
        ("➕ ساخت نظرسنجی", "adm:surveys:add"),
        ("↩️ پنل مدیریت", "adm:home"),
    )
    text = f"نظرسنجی‌ها ({total}) را انتخاب کنید:"
    if not surveys:
        text = "هنوز نظرسنجی‌ای ساخته نشده است."
    await _send_or_edit(target, text, keyboard)


async def _render_reports(
    target: Message | CallbackQuery,
    session_factory: async_sessionmaker,
    *,
    page: int = 0,
) -> None:
    async with session_factory() as session:
        total = await session.scalar(select(func.count(Survey.id))) or 0
        page_count = max(1, ceil(total / PAGE_SIZE))
        page = min(max(page, 0), page_count - 1)
        surveys = (
            await session.scalars(
                select(Survey).order_by(Survey.id.desc()).offset(page * PAGE_SIZE).limit(PAGE_SIZE)
            )
        ).all()
    items = [(_short_label(survey.title), f"adm:report:{survey.id}") for survey in surveys]
    keyboard = paginated_options(items, page=page, page_count=page_count, prefix="adm:reports:page")
    keyboard = _with_footer(keyboard, ("↩️ پنل مدیریت", "adm:home"))
    text = "نظرسنجی موردنظر برای گزارش را انتخاب کنید:"
    if not surveys:
        text = "هنوز نظرسنجی‌ای ساخته نشده است."
    await _send_or_edit(target, text, keyboard)


def build_admin_router(session_factory: async_sessionmaker, settings: Settings) -> Router:
    router = Router(name="admin")

    async def reject_message(message: Message) -> bool:
        if _is_admin(message.from_user.id, settings):
            return False
        await message.answer("شما دسترسی مدیریت ندارید.")
        return True

    async def reject_callback(callback: CallbackQuery) -> bool:
        if _is_admin(callback.from_user.id, settings):
            return False
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return True

    async def render_people_import(target: Message | CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        rows = data.get("import_rows", [])
        valid = [row for row in rows if not row.get("error")]
        invalid = [row for row in rows if row.get("error")]
        page_count = max(1, ceil(len(rows) / 15))
        page = min(max(int(data.get("import_preview_page", 0)), 0), page_count - 1)
        page_rows = rows[page * 15 : (page + 1) * 15]
        lines = [
            f"پیش‌نمایش ورود گروهی: {len(valid)} ردیف قابل ثبت، {len(invalid)} ردیف نیازمند اصلاح.",
            "هر ردیف را با وضعیتش بررسی کنید؛ ردیف‌های معتبر با تأیید و در یک تراکنش ثبت می‌شوند.",
        ]
        for row in page_rows:
            if row.get("error"):
                lines.append(
                    f"❌ ردیف {row['row']} · {row.get('internal_id') or 'بدون شناسه'}: {row['error']}"
                )
            else:
                lines.append(
                    f"✅ ردیف {row['row']} · {row['internal_id']} — {row['first_name']} {row['last_name']}"
                )
        buttons = []
        if page_count > 1:
            if page > 0:
                buttons.append(("⬅️ ردیف‌های قبلی", f"adm:people:import:page:{page - 1}"))
            buttons.append((f"صفحه {page + 1}/{page_count}", "noop"))
            if page + 1 < page_count:
                buttons.append(("ردیف‌های بعدی ➡️", f"adm:people:import:page:{page + 1}"))
        if valid:
            buttons.append((f"✅ ثبت {len(valid)} فرد معتبر", "adm:people:import:confirm"))
        buttons.append(("❌ لغو ورود گروهی", "adm:people:import:cancel"))
        await _send_or_edit(target, "\n".join(lines), inline_options(buttons))

    @router.message(Command("cancel"))
    async def cancel_flow(message: Message, state: FSMContext) -> None:
        await state.clear()
        is_admin = _is_admin(message.from_user.id, settings)
        if is_admin:
            await _delete_draft(session_factory, settings, message.from_user.id)
        await message.answer(
            "روند جاری لغو شد.", reply_markup=admin_menu() if is_admin else participant_menu()
        )

    @router.message(CommandStart())
    async def pass_start_to_user_router(message: Message, state: FSMContext) -> None:
        if _is_admin(message.from_user.id, settings):
            draft = await get_admin_draft(
                session_factory,
                platform=settings.bot_platform,
                platform_user_id=message.from_user.id,
            )
            valid_steps = {
                "person": {
                    PersonWizard.internal_id.state,
                    PersonWizard.first_name.state,
                    PersonWizard.last_name.state,
                    PersonWizard.description.state,
                },
                "person_edit": {PersonEditFlow.value.state},
                "people_import": {PersonBulkFlow.confirm.state},
                "survey": {
                    SurveyWizard.title.state,
                    SurveyWizard.starts_at.state,
                    SurveyWizard.ends_at.state,
                    SurveyWizard.description.state,
                    SurveyWizard.people.state,
                },
                "survey_edit": {
                    SurveyEditFlow.title.state,
                    SurveyEditFlow.description.state,
                    SurveyEditFlow.starts_at.state,
                    SurveyEditFlow.ends_at.state,
                    SurveyEditFlow.people.state,
                },
            }
            if draft and draft.step in valid_steps.get(draft.draft_type, set()):
                async with session_factory() as session:
                    await register_or_update_user(
                        session,
                        platform=settings.bot_platform,
                        platform_user_id=message.from_user.id,
                        full_name=message.from_user.full_name,
                        username=message.from_user.username,
                        is_admin=True,
                    )
                await state.set_state(draft.step)
                await state.set_data(draft.payload)
                prompts = {
                    PersonWizard.internal_id.state: "شناسهٔ داخلی فرد را بفرستید:",
                    PersonWizard.first_name.state: "نام فرد را بفرستید:",
                    PersonWizard.last_name.state: "نام خانوادگی را بفرستید:",
                    PersonWizard.description.state: "توضیح اختیاری را بفرستید یا /skip را ارسال کنید:",
                    SurveyWizard.title.state: "عنوان نظرسنجی را بفرستید:",
                    SurveyWizard.starts_at.state: "زمان شروع نظرسنجی را بفرستید:",
                    SurveyWizard.ends_at.state: "زمان پایان نظرسنجی را بفرستید:",
                    SurveyWizard.description.state: "توضیح اختیاری نظرسنجی را بفرستید یا /skip را ارسال کنید:",
                    SurveyEditFlow.title.state: "عنوان تازه را بفرستید یا /skip را بزنید تا عنوان فعلی بماند:",
                    SurveyEditFlow.description.state: "توضیح تازه، /skip برای حفظ توضیح فعلی یا /clear برای پاک‌کردن آن:",
                    SurveyEditFlow.starts_at.state: "زمان شروع تازه را بفرستید یا /skip را بزنید تا زمان فعلی بماند:",
                    SurveyEditFlow.ends_at.state: "زمان پایان تازه را بفرستید یا /skip را بزنید تا زمان فعلی بماند:",
                }
                if draft.step == PersonEditFlow.value.state:
                    field_names = {
                        "internal_id": "شناسهٔ داخلی",
                        "first_name": "نام",
                        "last_name": "نام خانوادگی",
                        "description": "توضیح",
                    }
                    field = draft.payload.get("field")
                    if field not in field_names:
                        await _delete_draft(session_factory, settings, message.from_user.id)
                        await state.clear()
                        raise SkipHandler
                    prompts[draft.step] = f"مقدار تازهٔ {field_names[field]} را بفرستید:"
                await message.answer(
                    "فرم نیمه‌کاره بازیابی شد. برای لغو /cancel را بفرستید.",
                    reply_markup=admin_menu(),
                )
                if draft.step == SurveyWizard.people.state:
                    await _render_survey_people(message, session_factory, state, page=0)
                elif draft.step == SurveyEditFlow.people.state:
                    await _render_survey_edit_people(message, session_factory, state, page=0)
                elif draft.step == PersonBulkFlow.confirm.state:
                    if (draft.payload or {}).get("import_rows"):
                        await render_people_import(message, state)
                    else:
                        await message.answer(
                            "برای ادامه، فایل CSV یا XLSX را به‌صورت پیوست بفرستید."
                        )
                else:
                    await message.answer(prompts[draft.step])
                return
            if draft:
                await _delete_draft(session_factory, settings, message.from_user.id)
        await state.clear()
        raise SkipHandler

    @router.message(F.text == "⚙️ پنل مدیریت")
    @router.message(F.text == "↩️ بازگشت به پنل مدیر")
    async def open_admin_home(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        await state.clear()
        await message.answer("پنل مدیریت — بخش موردنظر را انتخاب کنید.", reply_markup=admin_menu())

    @router.message(F.text == "🎭 حالت ارزیاب")
    async def open_participant_mode(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        await state.clear()
        await message.answer(
            "منوی ارزیاب فعال شد. برای بازگشت، دکمهٔ پایین را بزنید.",
            reply_markup=participant_menu(is_admin=True),
        )

    @router.message(F.text == "👥 مدیریت افراد")
    async def people_list(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        await state.clear()
        await state.update_data(people_query="")
        await _render_people(message, session_factory)

    @router.callback_query(F.data == "adm:people:import:start")
    async def begin_people_import(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        await state.clear()
        await state.set_state(PersonBulkFlow.confirm)
        await _persist_draft(
            session_factory, settings, callback.from_user.id, state, "people_import"
        )
        await callback.message.answer(
            "فایل CSV یا XLSX را بفرستید (حداکثر ۵ مگابایت و ۱۰۰۰ ردیف).\n"
            "ستون‌های لازم: شناسه داخلی، نام، نام خانوادگی؛ ستون توضیح اختیاری است.\n"
            "نمونهٔ سرستون CSV: شناسه داخلی,نام,نام خانوادگی,توضیح"
        )
        await callback.answer()

    @router.message(PersonBulkFlow.confirm, F.document)
    async def receive_people_import(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        document = message.document
        filename = document.file_name or ""
        if document.file_size and document.file_size > 5 * 1024 * 1024:
            await message.answer("حجم فایل نباید بیشتر از ۵ مگابایت باشد.")
            return
        file = await message.bot.get_file(document.file_id)
        content = await message.bot.download_file(file.file_path)
        try:
            parsed = parse_people_file(filename, content.read())
        except PeopleImportError as exc:
            await message.answer(str(exc))
            return
        ids = [str(row["internal_id"]) for row in parsed if not row.get("error")]
        from collections import Counter

        duplicate_ids = {value for value, count in Counter(ids).items() if count > 1}
        async with session_factory() as session:
            existing_ids = (
                set(
                    await session.scalars(
                        select(Person.internal_id).where(Person.internal_id.in_(set(ids)))
                    )
                )
                if ids
                else set()
            )
        for row in parsed:
            if row.get("error"):
                continue
            internal_id = str(row["internal_id"])
            if internal_id in duplicate_ids:
                row["error"] = "شناسه در خود فایل تکرار شده است"
            elif internal_id in existing_ids:
                row["error"] = "این شناسه قبلاً در سامانه ثبت شده است"
        await state.update_data(import_rows=parsed, import_filename=filename, import_preview_page=0)
        await _persist_draft(
            session_factory, settings, message.from_user.id, state, "people_import"
        )
        await render_people_import(message, state)

    @router.message(PersonBulkFlow.confirm)
    async def people_import_expected_file(message: Message) -> None:
        if await reject_message(message):
            return
        await message.answer("برای ادامه، فایل CSV یا XLSX را به‌صورت پیوست بفرستید.")

    @router.callback_query(F.data == "adm:people:import:cancel")
    async def cancel_people_import(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        await state.clear()
        await _delete_draft(session_factory, settings, callback.from_user.id)
        await callback.message.edit_text("ورود گروهی لغو شد.")
        await callback.answer()

    @router.callback_query(F.data == "adm:people:import:confirm")
    async def confirm_people_import(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != PersonBulkFlow.confirm.state:
            await callback.answer("پیش‌نمایش ورود گروهی منقضی شده است.", show_alert=True)
            return
        rows = (await state.get_data()).get("import_rows", [])
        valid_rows = [row for row in rows if not row.get("error")]
        if not valid_rows:
            await callback.answer("ردیف معتبری برای ثبت وجود ندارد.", show_alert=True)
            return
        ids = [str(row["internal_id"]) for row in valid_rows]
        try:
            async with session_factory() as session:
                existing = set(
                    await session.scalars(
                        select(Person.internal_id).where(Person.internal_id.in_(ids))
                    )
                )
                if existing:
                    await callback.answer(
                        "یک شناسه پس از پیش‌نمایش ثبت شده؛ فایل را دوباره بررسی کنید.",
                        show_alert=True,
                    )
                    return
                session.add_all(
                    [
                        Person(
                            internal_id=row["internal_id"],
                            first_name=row["first_name"],
                            last_name=row["last_name"],
                            display_name=f"{row['first_name']} {row['last_name']}",
                            description=row.get("description"),
                            is_active=True,
                        )
                        for row in valid_rows
                    ]
                )
                await session.execute(
                    delete(AdminDraft).where(
                        AdminDraft.platform == settings.bot_platform,
                        AdminDraft.platform_user_id == callback.from_user.id,
                    )
                )
                await session.commit()
        except IntegrityError:
            await callback.answer(
                "ثبت انجام نشد؛ یکی از شناسه‌ها تکراری شده است. فایل را دوباره بررسی کنید.",
                show_alert=True,
            )
            return
        await state.clear()
        await callback.message.edit_text(
            f"ورود گروهی تمام شد: {len(valid_rows)} فرد ثبت شد و {len(rows) - len(valid_rows)} ردیف نامعتبر ثبت نشد."
        )
        await callback.answer("ثبت شد")

    @router.callback_query(F.data.regexp(r"^adm:people:import:page:\d+$"))
    async def people_import_page(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != PersonBulkFlow.confirm.state:
            await callback.answer("پیش‌نمایش منقضی شده است.", show_alert=True)
            return
        await state.update_data(import_preview_page=int(callback.data.rsplit(":", 1)[1]))
        await render_people_import(callback, state)
        await callback.answer()

    @router.message(F.text == "➕ افزودن فرد")
    async def begin_person_wizard(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        await state.clear()
        await state.set_state(PersonWizard.internal_id)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "person")
        await message.answer("شناسهٔ داخلی فرد را بفرستید. برای لغو /cancel را ارسال کنید.")

    @router.message(PersonWizard.internal_id)
    async def person_internal_id(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        value = (message.text or "").strip()
        if not value or len(value) > 64:
            await message.answer("شناسه باید بین ۱ تا ۶۴ نویسه باشد. دوباره بفرستید:")
            return
        await state.update_data(internal_id=value)
        await state.set_state(PersonWizard.first_name)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "person")
        await message.answer("نام فرد را بفرستید:")

    @router.message(PersonWizard.first_name)
    async def person_first_name(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        value = (message.text or "").strip()
        if not value or len(value) > 100:
            await message.answer("نام باید بین ۱ تا ۱۰۰ نویسه باشد. دوباره بفرستید:")
            return
        await state.update_data(first_name=value)
        await state.set_state(PersonWizard.last_name)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "person")
        await message.answer("نام خانوادگی را بفرستید:")

    @router.message(PersonWizard.last_name)
    async def person_last_name(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        value = (message.text or "").strip()
        if not value or len(value) > 100:
            await message.answer("نام خانوادگی باید بین ۱ تا ۱۰۰ نویسه باشد. دوباره بفرستید:")
            return
        await state.update_data(last_name=value)
        await state.set_state(PersonWizard.description)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "person")
        await message.answer("توضیح اختیاری را بفرستید یا برای رد کردن /skip را ارسال کنید:")

    @router.message(PersonWizard.description)
    async def person_description(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        data = await state.get_data()
        description = None if message.text == "/skip" else (message.text or "").strip()[:2000]
        person = Person(
            internal_id=data["internal_id"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            display_name=f"{data['first_name']} {data['last_name']}",
            description=description,
        )
        async with session_factory() as session:
            existing = await session.scalar(
                select(Person.id).where(Person.internal_id == person.internal_id)
            )
            if existing:
                await message.answer(
                    "این شناسه قبلاً ثبت شده است. با /cancel روند را لغو و شناسهٔ دیگری انتخاب کنید."
                )
                return
            session.add(person)
            await session.execute(
                delete(AdminDraft).where(
                    AdminDraft.platform == settings.bot_platform,
                    AdminDraft.platform_user_id == message.from_user.id,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await message.answer(
                    "این شناسه قبلاً ثبت شده است. روند را با /cancel لغو و دوباره شروع کنید."
                )
                return
            display_name = person.display_name
        await state.clear()
        await message.answer(f"فرد «{display_name}» اضافه شد.", reply_markup=admin_menu())

    @router.callback_query(F.data == "adm:people:add")
    async def callback_add_person(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        await state.clear()
        await state.set_state(PersonWizard.internal_id)
        await _persist_draft(session_factory, settings, callback.from_user.id, state, "person")
        await callback.message.answer("شناسهٔ داخلی فرد را بفرستید. برای لغو /cancel را ارسال کنید.")
        await callback.answer()

    @router.callback_query(F.data == "adm:people:search")
    async def begin_people_search(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        await state.set_state(PersonWizard.search)
        await callback.message.answer("نام یا شناسهٔ داخلی را برای جست‌وجو بفرستید:")
        await callback.answer()

    @router.message(PersonWizard.search)
    async def search_people(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        query = (message.text or "").strip()
        await state.clear()
        await state.update_data(people_query=query)
        await _render_people(message, session_factory, query=query)

    @router.callback_query(F.data.regexp(r"^adm:people:page:\d+$"))
    async def people_page(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        page = int(callback.data.rsplit(":", 1)[1])
        query = (await state.get_data()).get("people_query", "")
        await _render_people(callback, session_factory, page=page, query=query)
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^adm:person:\d+$"))
    async def person_detail(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        try:
            person_id = int(callback.data.rsplit(":", 1)[1])
        except ValueError:
            await callback.answer("شناسهٔ فرد نامعتبر است.", show_alert=True)
            return
        async with session_factory() as session:
            person = await session.get(Person, person_id)
            if not person:
                await callback.answer("فرد پیدا نشد.", show_alert=True)
                return
            text = (
                f"👤 {person.display_name}\nشناسه: {person.internal_id}\n"
                f"وضعیت: {'فعال' if person.is_active else 'غیرفعال'}"
            )
            if person.description:
                text += f"\nتوضیح: {person.description}"
            keyboard = inline_options(
                [
                    ("✏️ ویرایش نام", f"adm:person:edit:first_name:{person.id}"),
                    ("✏️ ویرایش نام خانوادگی", f"adm:person:edit:last_name:{person.id}"),
                    ("🪪 ویرایش شناسه", f"adm:person:edit:internal_id:{person.id}"),
                    ("📝 ویرایش توضیح", f"adm:person:edit:description:{person.id}"),
                    (
                        "⏸ غیرفعال‌کردن" if person.is_active else "▶️ فعال‌کردن",
                        f"adm:person:toggle:{person.id}",
                    ),
                    ("↩️ بازگشت به فهرست", "adm:people:page:0"),
                ],
                columns=2,
            )
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(
        F.data.regexp(r"^adm:person:edit:(internal_id|first_name|last_name|description):\d+$")
    )
    async def begin_person_edit(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        _, _, _, field, person_id_text = callback.data.split(":")
        person_id = int(person_id_text)
        async with session_factory() as session:
            person = await session.get(Person, person_id)
            if not person:
                await callback.answer("فرد پیدا نشد.", show_alert=True)
                return
            current_values = {
                "internal_id": person.internal_id,
                "first_name": person.first_name,
                "last_name": person.last_name,
                "description": person.description or "ثبت نشده",
            }
        field_names = {
            "internal_id": "شناسهٔ داخلی",
            "first_name": "نام",
            "last_name": "نام خانوادگی",
            "description": "توضیح",
        }
        await state.clear()
        await state.update_data(person_id=person_id, field=field)
        await state.set_state(PersonEditFlow.value)
        await _persist_draft(session_factory, settings, callback.from_user.id, state, "person_edit")
        prompt = f"مقدار فعلی {field_names[field]}: {current_values[field]}\nمقدار تازه را بفرستید."
        if field == "description":
            prompt += " برای پاک‌کردن توضیح /skip را بفرستید."
        prompt += " برای لغو /cancel را بفرستید."
        await callback.message.answer(prompt)
        await callback.answer()

    @router.message(PersonEditFlow.value)
    async def save_person_edit(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        data = await state.get_data()
        field = data["field"]
        raw_value = (message.text or "").strip()
        if field == "description" and raw_value == "/skip":
            value = None
        elif not raw_value:
            await message.answer("مقدار نمی‌تواند خالی باشد. دوباره بفرستید:")
            return
        elif field == "internal_id" and len(raw_value) > 64:
            await message.answer("شناسه حداکثر می‌تواند ۶۴ نویسه باشد. دوباره بفرستید:")
            return
        elif field in {"first_name", "last_name"} and len(raw_value) > 100:
            await message.answer("نام حداکثر می‌تواند ۱۰۰ نویسه باشد. دوباره بفرستید:")
            return
        elif field == "description" and len(raw_value) > 2000:
            await message.answer("توضیح حداکثر می‌تواند ۲۰۰۰ نویسه باشد. دوباره بفرستید:")
            return
        else:
            value = raw_value

        async with session_factory() as session:
            person = await session.get(Person, data["person_id"])
            if not person:
                await state.clear()
                await _delete_draft(session_factory, settings, message.from_user.id)
                await message.answer("فرد دیگر پیدا نمی‌شود؛ ویرایش لغو شد.")
                return
            if field == "internal_id":
                duplicate = await session.scalar(
                    select(Person.id).where(
                        Person.internal_id == value,
                        Person.id != person.id,
                    )
                )
                if duplicate:
                    await message.answer("این شناسه قبلاً استفاده شده است. شناسهٔ دیگری بفرستید:")
                    return
                person.internal_id = value
            elif field == "first_name":
                person.first_name = value
                person.display_name = f"{person.first_name} {person.last_name}"
            elif field == "last_name":
                person.last_name = value
                person.display_name = f"{person.first_name} {person.last_name}"
            elif field == "description":
                person.description = value
            await session.execute(
                delete(AdminDraft).where(
                    AdminDraft.platform == settings.bot_platform,
                    AdminDraft.platform_user_id == message.from_user.id,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await message.answer("ثبت تغییر انجام نشد؛ مقدار شناسه احتمالاً تکراری است.")
                return
            display_name = person.display_name
        await state.clear()
        await message.answer(f"اطلاعات «{display_name}» به‌روزرسانی شد.", reply_markup=admin_menu())

    @router.callback_query(F.data.regexp(r"^adm:person:toggle:\d+$"))
    async def toggle_person(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        person_id = int(callback.data.rsplit(":", 1)[1])
        async with session_factory() as session:
            person = await session.get(Person, person_id)
            if not person:
                await callback.answer("فرد پیدا نشد.", show_alert=True)
                return
            person.is_active = not person.is_active
            await session.commit()
            text = (
                f"👤 {person.display_name}\nشناسه: {person.internal_id}\n"
                f"وضعیت: {'فعال' if person.is_active else 'غیرفعال'}"
            )
            if person.description:
                text += f"\nتوضیح: {person.description}"
            keyboard = inline_options(
                [
                    (
                        "⏸ غیرفعال‌کردن" if person.is_active else "▶️ فعال‌کردن",
                        f"adm:person:toggle:{person.id}",
                    ),
                    ("↩️ بازگشت به فهرست", "adm:people:page:0"),
                ]
            )
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("وضعیت فرد تغییر کرد.")

    @router.message(F.text == "🗳 مدیریت نظرسنجی‌ها")
    async def survey_list(message: Message) -> None:
        if await reject_message(message):
            return
        await _render_surveys(message, session_factory)

    @router.message(F.text == "➕ ساخت نظرسنجی")
    async def begin_survey_wizard(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        await state.clear()
        await state.set_state(SurveyWizard.title)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey")
        await message.answer("عنوان نظرسنجی را بفرستید. برای لغو /cancel را ارسال کنید.")

    @router.callback_query(F.data == "adm:surveys:add")
    async def callback_add_survey(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        await state.clear()
        await state.set_state(SurveyWizard.title)
        await _persist_draft(session_factory, settings, callback.from_user.id, state, "survey")
        await callback.message.answer("عنوان نظرسنجی را بفرستید. برای لغو /cancel را ارسال کنید.")
        await callback.answer()

    @router.message(SurveyWizard.title)
    async def survey_title(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        title = (message.text or "").strip()
        if not title or len(title) > 200:
            await message.answer("عنوان باید بین ۱ تا ۲۰۰ نویسه باشد. دوباره بفرستید:")
            return
        await state.update_data(title=title)
        await state.set_state(SurveyWizard.starts_at)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey")
        await message.answer(
            "زمان شروع را بفرستید (مثل 2026-10-08T09:00:00؛ زمان بدون منطقهٔ زمانی، به وقت تنظیم‌شدهٔ ربات است):"
        )

    @router.message(SurveyWizard.starts_at)
    async def survey_start(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        try:
            starts_at = _parse_datetime(message.text or "", settings.timezone)
        except (ValueError, KeyError):
            await message.answer("زمان معتبر نیست. از قالب YYYY-MM-DDTHH:MM:SS استفاده کنید:")
            return
        await state.update_data(starts_at=starts_at.isoformat())
        await state.set_state(SurveyWizard.ends_at)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey")
        await message.answer("زمان پایان را بفرستید:")

    @router.message(SurveyWizard.ends_at)
    async def survey_end(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        try:
            ends_at = _parse_datetime(message.text or "", settings.timezone)
            starts_at = datetime.fromisoformat((await state.get_data())["starts_at"])
        except (ValueError, KeyError):
            await message.answer("زمان معتبر نیست. از قالب YYYY-MM-DDTHH:MM:SS استفاده کنید:")
            return
        if ends_at <= starts_at:
            await message.answer("زمان پایان باید بعد از شروع باشد. زمان پایان را دوباره بفرستید:")
            return
        await state.update_data(ends_at=ends_at.isoformat())
        await state.set_state(SurveyWizard.description)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey")
        await message.answer("توضیح اختیاری نظرسنجی را بفرستید یا /skip را ارسال کنید:")

    @router.message(SurveyWizard.description)
    async def survey_description(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            await state.clear()
            return
        description = None if message.text == "/skip" else (message.text or "").strip()[:4000]
        await state.update_data(description=description, selected_people=[])
        await state.set_state(SurveyWizard.people)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey")
        await _render_survey_people(message, session_factory, state, page=0)

    async def _render_survey_people(
        target: Message | CallbackQuery,
        sessions: async_sessionmaker,
        state: FSMContext,
        *,
        page: int,
    ) -> None:
        async with sessions() as session:
            total = (
                await session.scalar(
                    select(func.count(Person.id)).where(Person.is_active.is_(True))
                )
                or 0
            )
            page_count = max(1, ceil(total / PAGE_SIZE))
            page = min(max(page, 0), page_count - 1)
            people = (
                await session.scalars(
                    select(Person)
                    .where(Person.is_active.is_(True))
                    .order_by(Person.display_name)
                    .offset(page * PAGE_SIZE)
                    .limit(PAGE_SIZE)
                )
            ).all()
        data = await state.get_data()
        selected = set(data.get("selected_people", []))
        if not people:
            text = "هیچ فرد فعالی وجود ندارد. ابتدا از بخش مدیریت افراد، افراد را اضافه کنید."
            keyboard = inline_options([("↩️ پنل مدیریت", "adm:home")])
        else:
            rows = [
                (
                    _short_label(f"{'✅' if person.id in selected else '▫️'} {person.display_name}"),
                    f"adm:survey:pick:{page}:{person.id}",
                )
                for person in people
            ]
            keyboard = paginated_options(
                rows, page=page, page_count=page_count, prefix="adm:survey:people:page"
            )
            keyboard = _with_footer(
                keyboard,
                (f"✅ پایان انتخاب ({len(selected)} نفر)", "adm:survey:finish"),
                ("❌ لغو ساخت", "adm:cancel"),
            )
            text = (
                "افراد این نظرسنجی را انتخاب کنید؛ برای افزودن یا برداشتن، نام را بزنید.\n"
                f"تعداد انتخاب‌شده: {len(selected)}"
            )
        await _send_or_edit(target, text, keyboard)

    async def _render_survey_edit_people(
        target: Message | CallbackQuery,
        sessions: async_sessionmaker,
        state: FSMContext,
        *,
        page: int,
    ) -> None:
        data = await state.get_data()
        selected = set(data.get("selected_people", []))
        async with sessions() as session:
            total = await session.scalar(select(func.count(Person.id))) or 0
            page_count = max(1, ceil(total / PAGE_SIZE))
            page = min(max(page, 0), page_count - 1)
            people = (
                await session.scalars(
                    select(Person)
                    .order_by(Person.display_name)
                    .offset(page * PAGE_SIZE)
                    .limit(PAGE_SIZE)
                )
            ).all()
        if not people:
            text = "فردی برای انتخاب وجود ندارد."
            keyboard = inline_options([("↩️ جزئیات", f"adm:survey:{data['survey_id']}")])
        else:
            rows = [
                (
                    _short_label(
                        f"{'✅' if p.id in selected else '▫️'} {p.display_name}{'' if p.is_active else ' (غیرفعال)'}"
                    ),
                    f"adm:survey:edit:pick:{page}:{p.id}",
                )
                for p in people
            ]
            keyboard = paginated_options(
                rows, page=page, page_count=page_count, prefix="adm:survey:edit:people:page"
            )
            keyboard = _with_footer(
                keyboard,
                (f"✅ ذخیرهٔ افراد ({len(selected)})", "adm:survey:edit:finish"),
                ("❌ لغو ویرایش", "adm:cancel"),
            )
            text = (
                "افراد نظرسنجی را انتخاب کنید. افراد غیرفعال فقط قابل برداشتن هستند.\n"
                + f"انتخاب‌شده: {len(selected)}"
            )
        await _send_or_edit(target, text, keyboard)

    async def _survey_for_callback(callback: CallbackQuery, survey_id: int):
        async with session_factory() as session:
            survey = await session.get(Survey, survey_id)
            if survey is None:
                return None, 0
            votes = (
                await session.scalar(select(func.count(Vote.id)).where(Vote.survey_id == survey_id))
                or 0
            )
            return survey, votes

    @router.callback_query(F.data.regexp(r"^adm:survey:edit:\d+$"))
    async def begin_survey_edit(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        survey_id = int(callback.data.rsplit(":", 1)[1])
        survey, votes = await _survey_for_callback(callback, survey_id)
        if survey is None:
            await callback.answer("نظرسنجی پیدا نشد.", show_alert=True)
            return
        if survey_status(survey) != SurveyStatus.SCHEDULED or votes:
            await callback.answer(
                "فقط نظرسنجی زمان‌بندی‌شدهٔ بدون رأی قابل ویرایش است.", show_alert=True
            )
            return
        async with session_factory() as session:
            selected = list(
                await session.scalars(
                    select(SurveyPerson.person_id).where(SurveyPerson.survey_id == survey_id)
                )
            )
        await state.clear()
        await state.update_data(
            survey_id=survey_id,
            title=survey.title,
            description=survey.description,
            starts_at=_as_utc_if_naive(survey.starts_at).isoformat(),
            ends_at=_as_utc_if_naive(survey.ends_at).isoformat(),
            selected_people=selected,
        )
        await state.set_state(SurveyEditFlow.title)
        await _persist_draft(session_factory, settings, callback.from_user.id, state, "survey_edit")
        await callback.message.answer(
            "عنوان تازه را بفرستید یا /skip را بزنید تا عنوان فعلی بماند:"
        )
        await callback.answer()

    @router.message(SurveyEditFlow.title)
    async def edit_survey_title(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        value = (message.text or "").strip()
        if value != "/skip":
            if not value or len(value) > 200:
                await message.answer("عنوان باید بین ۱ تا ۲۰۰ نویسه باشد:")
                return
            await state.update_data(title=value)
        await state.set_state(SurveyEditFlow.description)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey_edit")
        await message.answer("توضیح تازه، /skip برای حفظ یا /clear برای پاک‌کردن:")

    @router.message(SurveyEditFlow.description)
    async def edit_survey_description(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        value = (message.text or "").strip()
        if value == "/clear":
            await state.update_data(description=None)
        elif value != "/skip":
            if len(value) > 4000:
                await message.answer("توضیح حداکثر ۴۰۰۰ نویسه است:")
                return
            await state.update_data(description=value or None)
        await state.set_state(SurveyEditFlow.starts_at)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey_edit")
        await message.answer("زمان شروع جدید را بفرستید یا /skip:")

    @router.message(SurveyEditFlow.starts_at)
    async def edit_survey_start(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        value = (message.text or "").strip()
        if value != "/skip":
            try:
                parsed = _parse_datetime(value, settings.timezone)
            except (ValueError, KeyError):
                await message.answer("زمان معتبر نیست؛ قالب YYYY-MM-DDTHH:MM:SS:")
                return
            await state.update_data(starts_at=parsed.isoformat())
        await state.set_state(SurveyEditFlow.ends_at)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey_edit")
        await message.answer("زمان پایان جدید را بفرستید یا /skip:")

    @router.message(SurveyEditFlow.ends_at)
    async def edit_survey_end(message: Message, state: FSMContext) -> None:
        if await reject_message(message):
            return
        data = await state.get_data()
        value = (message.text or "").strip()
        if value != "/skip":
            try:
                parsed = _parse_datetime(value, settings.timezone)
            except (ValueError, KeyError):
                await message.answer("زمان معتبر نیست؛ قالب YYYY-MM-DDTHH:MM:SS:")
                return
            await state.update_data(ends_at=parsed.isoformat())
        data = await state.get_data()
        try:
            start, end = (
                datetime.fromisoformat(data["starts_at"]),
                datetime.fromisoformat(data["ends_at"]),
            )
            if _as_utc_if_naive(end) <= _as_utc_if_naive(start):
                raise ValueError
            if _as_utc_if_naive(start) <= datetime.now(timezone.utc):
                raise ValueError
        except ValueError:
            await message.answer(
                "بازه باید معتبر باشد و شروع در آینده قرار بگیرد. زمان پایان را دوباره بفرستید یا /skip:"
            )
            return
        await state.set_state(SurveyEditFlow.people)
        await _persist_draft(session_factory, settings, message.from_user.id, state, "survey_edit")
        await _render_survey_edit_people(message, session_factory, state, page=0)

    @router.callback_query(F.data.regexp(r"^adm:survey:edit:people:page:\d+$"))
    async def edit_survey_people_page(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != SurveyEditFlow.people.state:
            await callback.answer("فرم ویرایش فعال نیست.", show_alert=True)
            return
        await _render_survey_edit_people(
            callback, session_factory, state, page=int(callback.data.rsplit(":", 1)[1])
        )
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^adm:survey:edit:pick:\d+:\d+$"))
    async def toggle_edit_survey_person(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != SurveyEditFlow.people.state:
            await callback.answer("فرم ویرایش فعال نیست.", show_alert=True)
            return
        _, _, _, _, page_text, person_text = callback.data.split(":")
        page, person_id = int(page_text), int(person_text)
        async with session_factory() as session:
            person = await session.get(Person, person_id)
        data = await state.get_data()
        selected = set(data.get("selected_people", []))
        if person is None or (person_id not in selected and not person.is_active):
            await callback.answer("فرد فعال نیست و نمی‌توان افزود.", show_alert=True)
            return
        if person_id in selected:
            selected.remove(person_id)
        else:
            selected.add(person_id)
        await state.update_data(selected_people=sorted(selected))
        await _persist_draft(session_factory, settings, callback.from_user.id, state, "survey_edit")
        await _render_survey_edit_people(callback, session_factory, state, page=page)
        await callback.answer()

    @router.callback_query(F.data == "adm:survey:edit:finish")
    async def finish_survey_edit(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != SurveyEditFlow.people.state:
            await callback.answer("فرم ویرایش فعال نیست.", show_alert=True)
            return
        data = await state.get_data()
        ids = data.get("selected_people", [])
        if not ids:
            await callback.answer("حداقل یک فرد لازم است.", show_alert=True)
            return
        start, end = (
            datetime.fromisoformat(data["starts_at"]),
            datetime.fromisoformat(data["ends_at"]),
        )
        async with session_factory() as session:
            survey = await session.get(Survey, data["survey_id"])
            votes = (
                await session.scalar(
                    select(func.count(Vote.id)).where(Vote.survey_id == data["survey_id"])
                )
                or 0
            )
            people = (
                await session.scalars(
                    select(Person).where(Person.id.in_(ids), Person.is_active.is_(True))
                )
            ).all()
            if survey is None or survey_status(survey) != SurveyStatus.SCHEDULED or votes:
                await callback.answer("شرایط ویرایش تغییر کرده؛ ویرایش انجام نشد.", show_alert=True)
                return
            if (
                len(people) != len(set(ids))
                or _as_utc_if_naive(start) <= datetime.now(timezone.utc)
                or _as_utc_if_naive(end) <= _as_utc_if_naive(start)
            ):
                await callback.answer("افراد یا بازهٔ زمانی معتبر نیست.", show_alert=True)
                return
            survey.title = data["title"]
            survey.description = data.get("description")
            survey.starts_at = start
            survey.ends_at = end
            await session.execute(delete(SurveyPerson).where(SurveyPerson.survey_id == survey.id))
            session.add_all([SurveyPerson(survey_id=survey.id, person_id=p.id) for p in people])
            await session.execute(
                delete(AdminDraft).where(
                    AdminDraft.platform == settings.bot_platform,
                    AdminDraft.platform_user_id == callback.from_user.id,
                )
            )
            await session.commit()
        await state.clear()
        await callback.message.edit_text("تغییرات نظرسنجی ذخیره شد.")
        await callback.answer("ذخیره شد")

    @router.callback_query(F.data.regexp(r"^adm:survey:cancel:\d+$"))
    async def ask_cancel_survey(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        survey_id = int(callback.data.rsplit(":", 1)[1])
        survey, _ = await _survey_for_callback(callback, survey_id)
        if survey is None or survey_status(survey) not in {
            SurveyStatus.SCHEDULED,
            SurveyStatus.ACTIVE,
        }:
            await callback.answer("این نظرسنجی قابل لغو نیست.", show_alert=True)
            return
        await callback.message.edit_text(
            f"نظرسنجی «{survey.title}» لغو شود؟ رأی‌ها و گزارش‌های قبلی حفظ می‌شوند.",
            reply_markup=inline_options(
                [
                    ("⚠️ تأیید لغو", f"adm:survey:cancel:confirm:{survey_id}"),
                    ("↩️ بازگشت", f"adm:survey:{survey_id}"),
                ]
            ),
        )
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^adm:survey:cancel:confirm:\d+$"))
    async def confirm_cancel_survey(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        survey_id = int(callback.data.rsplit(":", 1)[1])
        async with session_factory() as session:
            survey = await session.get(Survey, survey_id)
            if survey is None or survey_status(survey) not in {
                SurveyStatus.SCHEDULED,
                SurveyStatus.ACTIVE,
            }:
                await callback.answer("این نظرسنجی قابل لغو نیست.", show_alert=True)
                return
            survey.status = SurveyStatus.CANCELLED.value
            title = survey.title
            await session.commit()
        await callback.message.edit_text(
            f"نظرسنجی «{title}» لغو شد. رأی‌ها و گزارش‌های قبلی حفظ شده‌اند.",
            reply_markup=inline_options(
                [
                    ("📊 گزارش", f"adm:report:{survey_id}"),
                    ("📥 اکسل", f"adm:export:{survey_id}"),
                    ("↩️ جزئیات", f"adm:survey:{survey_id}"),
                ]
            ),
        )
        await callback.answer("لغو شد")

    @router.callback_query(F.data.regexp(r"^adm:survey:people:page:\d+$"))
    async def survey_people_page(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != SurveyWizard.people.state:
            await callback.answer("روند ساخت نظرسنجی تمام شده است.", show_alert=True)
            return
        page = int(callback.data.rsplit(":", 1)[1])
        await _render_survey_people(callback, session_factory, state, page=page)
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^adm:survey:pick:\d+:\d+$"))
    async def toggle_survey_person(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != SurveyWizard.people.state:
            await callback.answer("روند ساخت نظرسنجی تمام شده است.", show_alert=True)
            return
        _, _, _, page_text, person_text = callback.data.split(":")
        page = int(page_text)
        person_id = int(person_text)
        async with session_factory() as session:
            person = await session.scalar(
                select(Person.id).where(Person.id == person_id, Person.is_active.is_(True))
            )
        if person is None:
            await callback.answer("این فرد دیگر فعال نیست.", show_alert=True)
            return
        data = await state.get_data()
        selected = set(data.get("selected_people", []))
        if person_id in selected:
            selected.remove(person_id)
        else:
            selected.add(person_id)
        await state.update_data(selected_people=sorted(selected))
        await _persist_draft(session_factory, settings, callback.from_user.id, state, "survey")
        await _render_survey_people(callback, session_factory, state, page=page)
        await callback.answer()

    @router.callback_query(F.data == "adm:survey:finish")
    async def finish_survey(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        if await state.get_state() != SurveyWizard.people.state:
            await callback.answer("روند ساخت نظرسنجی تمام شده است.", show_alert=True)
            return
        data = await state.get_data()
        selected_ids = data.get("selected_people", [])
        if not selected_ids:
            await callback.answer("حداقل یک فرد را انتخاب کنید.", show_alert=True)
            return
        async with session_factory() as session:
            people = (
                await session.scalars(
                    select(Person).where(Person.id.in_(selected_ids), Person.is_active.is_(True))
                )
            ).all()
            if not people:
                await callback.answer("افراد انتخاب‌شده دیگر فعال نیستند.", show_alert=True)
                return
            survey = Survey(
                title=data["title"],
                description=data.get("description"),
                starts_at=datetime.fromisoformat(data["starts_at"]),
                ends_at=datetime.fromisoformat(data["ends_at"]),
                status=SurveyStatus.SCHEDULED.value,
            )
            session.add(survey)
            await session.flush()
            for person in people:
                session.add(SurveyPerson(survey_id=survey.id, person_id=person.id))
            await session.execute(
                delete(AdminDraft).where(
                    AdminDraft.platform == settings.bot_platform,
                    AdminDraft.platform_user_id == callback.from_user.id,
                )
            )
            await session.commit()
            survey_id = survey.id
        await state.clear()
        await callback.message.edit_text(
            f"نظرسنجی «{data['title']}» ساخته شد.\nشناسه: {survey_id}\nافراد: {len(people)}"
        )
        await callback.answer("نظرسنجی ساخته شد.")

    @router.message(F.text == "📈 گزارش‌ها")
    @router.message(Command("reports"))
    async def reports(message: Message) -> None:
        if await reject_message(message):
            return
        await _render_reports(message, session_factory)

    @router.callback_query(F.data.regexp(r"^adm:surveys:page:\d+$"))
    async def survey_page(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        page = int(callback.data.rsplit(":", 1)[1])
        await _render_surveys(callback, session_factory, page=page)
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^adm:reports:page:\d+$"))
    async def reports_page(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        page = int(callback.data.rsplit(":", 1)[1])
        await _render_reports(callback, session_factory, page=page)
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^adm:survey:\d+$"))
    async def survey_detail(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        survey_id = int(callback.data.rsplit(":", 1)[1])
        async with session_factory() as session:
            survey = await session.get(Survey, survey_id)
            if not survey:
                await callback.answer("نظرسنجی پیدا نشد.", show_alert=True)
                return
            people_count = (
                await session.scalar(
                    select(func.count(SurveyPerson.id)).where(SurveyPerson.survey_id == survey_id)
                )
                or 0
            )
            vote_count = (
                await session.scalar(select(func.count(Vote.id)).where(Vote.survey_id == survey_id))
                or 0
            )
            details = (
                f"🗳 {survey.title}\nوضعیت: {_status_label(survey)}\n"
                f"شروع: {survey.starts_at}\nپایان: {survey.ends_at}\n"
                f"افراد: {people_count}\nرأی‌ها: {vote_count}"
            )
            if survey.description:
                details += f"\nتوضیح: {survey.description}"
        buttons = []
        if survey_status(survey) == SurveyStatus.SCHEDULED and vote_count == 0:
            buttons.append(("✏️ ویرایش", f"adm:survey:edit:{survey_id}"))
        if survey_status(survey) in {SurveyStatus.SCHEDULED, SurveyStatus.ACTIVE}:
            buttons.append(("⛔ لغو نظرسنجی", f"adm:survey:cancel:{survey_id}"))
        buttons.extend(
            [
                ("📊 دیدن گزارش", f"adm:report:{survey_id}"),
                ("📥 دریافت اکسل", f"adm:export:{survey_id}"),
                ("↩️ بازگشت به فهرست", "adm:surveys:page:0"),
            ]
        )
        keyboard = inline_options(buttons)
        await callback.message.edit_text(details, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^adm:report:\d+$"))
    async def report(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        survey_id = int(callback.data.rsplit(":", 1)[1])
        async with session_factory() as session:
            survey = await session.get(Survey, survey_id)
            if not survey:
                await callback.answer("نظرسنجی پیدا نشد.", show_alert=True)
                return
            stats = await survey_statistics(session, survey_id)
            assigned = (
                await session.scalar(
                    select(func.count(SurveyPerson.id)).where(SurveyPerson.survey_id == survey_id)
                )
                or 0
            )
            total_votes = (
                await session.scalar(select(func.count(Vote.id)).where(Vote.survey_id == survey_id))
                or 0
            )
            voter_count = (
                await session.scalar(
                    select(func.count(func.distinct(Vote.user_id))).where(
                        Vote.survey_id == survey_id
                    )
                )
                or 0
            )
            title = survey.title
        rated_people = sum(1 for item in stats if item["votes"])
        progress = f"پیشرفت افراد: {rated_people}/{assigned} ({(rated_people / assigned * 100) if assigned else 0:.0f}٪)"
        summary = "\n".join(
            f"{item['name']}: {item['votes']} رأی، میانگین {item['average']:.2f}" for item in stats
        )
        keyboard = inline_options(
            [
                ("📥 دریافت اکسل", f"adm:export:{survey_id}"),
                ("↩️ جزئیات نظرسنجی", f"adm:survey:{survey_id}"),
            ]
        )
        await callback.message.answer(
            f"گزارش «{title}»\nافراد دارای رأی: {rated_people}/{assigned}\n{progress}\n"
            f"کل رأی‌ها: {total_votes} · رأی‌دهندگان یکتا: {voter_count}\n\n"
            f"{summary or 'رأیی ثبت نشده است.'}",
            reply_markup=keyboard,
        )
        await callback.answer()

    @router.message(Command("export"))
    async def export_command(message: Message) -> None:
        if await reject_message(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("قالب درست: /export شناسه")
            return
        await send_export(message, session_factory, int(parts[1]))

    @router.callback_query(F.data.regexp(r"^adm:export:\d+$"))
    async def export_callback(callback: CallbackQuery) -> None:
        if await reject_callback(callback):
            return
        survey_id = int(callback.data.rsplit(":", 1)[1])
        await send_export(callback.message, session_factory, survey_id)
        await callback.answer()

    @router.message(Command("addperson"))
    async def legacy_add_person(message: Message) -> None:
        if await reject_message(message):
            return
        try:
            raw = (message.text or "").split(maxsplit=1)[1]
            internal_id, first_name, last_name = [part.strip() for part in raw.split("|", 2)]
            if not internal_id or not first_name or not last_name:
                raise ValueError
            async with session_factory() as session:
                if await session.scalar(select(Person.id).where(Person.internal_id == internal_id)):
                    await message.answer("این شناسه قبلاً ثبت شده است.")
                    return
                session.add(
                    Person(
                        internal_id=internal_id,
                        first_name=first_name,
                        last_name=last_name,
                        display_name=f"{first_name} {last_name}",
                    )
                )
                await session.commit()
            await message.answer(f"فرد «{first_name} {last_name}» اضافه شد.")
        except (ValueError, IndexError):
            await message.answer("قالب: /addperson شناسه|نام|نام‌خانوادگی")

    @router.message(Command("addsurvey"))
    async def legacy_add_survey(message: Message) -> None:
        if await reject_message(message):
            return
        try:
            raw = (message.text or "").split(maxsplit=1)[1]
            title, start_text, end_text, people_text = [part.strip() for part in raw.split("|", 3)]
            starts_at = _parse_datetime(start_text, settings.timezone)
            ends_at = _parse_datetime(end_text, settings.timezone)
            if ends_at <= starts_at:
                raise ValueError
            person_ids = {int(value.strip()) for value in people_text.split(",") if value.strip()}
            if not title or not person_ids:
                raise ValueError
            async with session_factory() as session:
                people = (
                    await session.scalars(
                        select(Person).where(Person.id.in_(person_ids), Person.is_active.is_(True))
                    )
                ).all()
                if len(people) != len(person_ids):
                    await message.answer("بعضی شناسه‌ها وجود ندارند یا غیرفعال‌اند.")
                    return
                survey = Survey(
                    title=title,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status=SurveyStatus.SCHEDULED.value,
                )
                session.add(survey)
                await session.flush()
                for person in people:
                    session.add(SurveyPerson(survey_id=survey.id, person_id=person.id))
                await session.commit()
                survey_id = survey.id
            await message.answer(f"نظرسنجی ساخته شد. شناسه: {survey_id}")
        except (ValueError, IndexError):
            await message.answer(
                "قالب: /addsurvey عنوان|شروع ISO|پایان ISO|شناسه افراد\n"
                "نمونه: /addsurvey ارزیابی|2026-10-08T09:00:00+03:30|"
                "2026-10-09T17:00:00+03:30|1,2"
            )

    @router.callback_query(F.data == "adm:home")
    async def admin_home_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        await state.clear()
        await callback.message.answer("پنل مدیریت", reply_markup=admin_menu())
        await callback.answer()

    @router.callback_query(F.data == "adm:cancel")
    async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if await reject_callback(callback):
            return
        await state.clear()
        await _delete_draft(session_factory, settings, callback.from_user.id)
        await callback.message.answer("فرم جاری لغو شد.", reply_markup=admin_menu())
        await callback.answer()

    @router.callback_query(F.data == "noop")
    async def noop(callback: CallbackQuery) -> None:
        await callback.answer()

    return router


async def send_export(
    target: Message,
    session_factory: async_sessionmaker,
    survey_id: int,
) -> None:
    async with session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if survey is None:
            await target.answer("نظرسنجی پیدا نشد.")
            return
        data = await build_survey_workbook(session, survey_id)
        title = survey.title
    safe_name = "".join(char for char in title if char.isalnum() or char in " -_")[:60] or "report"
    await target.answer_document(BufferedInputFile(data.read(), filename=f"{safe_name}.xlsx"))
