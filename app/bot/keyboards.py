from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.services.datetime_parser import PERSIAN_MONTHS, gregorian_to_jalali


def participant_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📝 نظرسنجی‌های فعال"), KeyboardButton(text="📊 امتیازهای من")],
        [KeyboardButton(text="ℹ️ راهنما")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="↩️ بازگشت به پنل مدیر")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu(is_owner: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="👥 مدیریت افراد"), KeyboardButton(text="➕ افزودن فرد")],
        [KeyboardButton(text="🗳 مدیریت نظرسنجی‌ها"), KeyboardButton(text="➕ ساخت نظرسنجی")],
        [KeyboardButton(text="📈 گزارش‌ها"), KeyboardButton(text="🎭 حالت ارزیاب")],
    ]
    if is_owner:
        keyboard.append([KeyboardButton(text="🛡 مدیریت مدیران"), KeyboardButton(text="📜 وقایع سیستم")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def inline_options(items: list[tuple[str, str]], columns: int = 1) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=label, callback_data=data) for label, data in items]
    return InlineKeyboardMarkup(
        inline_keyboard=[buttons[i : i + columns] for i in range(0, len(buttons), columns)]
    )


def paginated_options(
    items: list[tuple[str, str]],
    *,
    page: int,
    page_count: int,
    prefix: str,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=data)] for label, data in items
    ]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"{prefix}:{page - 1}"))
    if page_count > 1:
        navigation.append(InlineKeyboardButton(text=f"{page + 1}/{page_count}", callback_data="noop"))
    if page + 1 < page_count:
        navigation.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"{prefix}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def datetime_start_keyboard(now: datetime, is_edit: bool = False) -> InlineKeyboardMarkup:
    """Build quick start date/time selection keyboard."""
    tomorrow = now + timedelta(days=1)
    dayafter = now + timedelta(days=2)
    _t_jy, t_jm, t_jd = gregorian_to_jalali(now.year, now.month, now.day)
    _tm_jy, tm_jm, tm_jd = gregorian_to_jalali(tomorrow.year, tomorrow.month, tomorrow.day)
    _da_jy, da_jm, da_jd = gregorian_to_jalali(dayafter.year, dayafter.month, dayafter.day)

    buttons = [
        [
            InlineKeyboardButton(text=f"📅 امروز ({t_jd} {PERSIAN_MONTHS[t_jm]})", callback_data="adm:dt:date:today"),
            InlineKeyboardButton(text=f"📅 فردا ({tm_jd} {PERSIAN_MONTHS[tm_jm]})", callback_data="adm:dt:date:tomorrow"),
            InlineKeyboardButton(text=f"📅 پس‌فردا ({da_jd} {PERSIAN_MONTHS[da_jm]})", callback_data="adm:dt:date:dayafter"),
        ],
        [
            InlineKeyboardButton(text="⏰ ۱ ساعت بعد", callback_data="adm:dt:quick:1h"),
            InlineKeyboardButton(text="⏰ ۲ ساعت بعد", callback_data="adm:dt:quick:2h"),
            InlineKeyboardButton(text="⏰ فردا ۰۹:۰۰", callback_data="adm:dt:quick:tomorrow_9"),
        ],
    ]
    if is_edit:
        buttons.append([InlineKeyboardButton(text="⏭ بدون تغییر زمان شروع (/skip)", callback_data="adm:dt:skip")])
    buttons.append([InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def datetime_time_keyboard(is_edit: bool = False, allow_back: bool = True) -> InlineKeyboardMarkup:
    """Build quick hour/time selection keyboard."""
    buttons = [
        [
            InlineKeyboardButton(text="۰۸:۰۰", callback_data="adm:dt:time:08:00"),
            InlineKeyboardButton(text="۰۹:۰۰", callback_data="adm:dt:time:09:00"),
            InlineKeyboardButton(text="۱۰:۰۰", callback_data="adm:dt:time:10:00"),
            InlineKeyboardButton(text="۱۲:۰۰", callback_data="adm:dt:time:12:00"),
        ],
        [
            InlineKeyboardButton(text="۱۴:۰۰", callback_data="adm:dt:time:14:00"),
            InlineKeyboardButton(text="۱۶:۰۰", callback_data="adm:dt:time:16:00"),
            InlineKeyboardButton(text="۱۸:۰۰", callback_data="adm:dt:time:18:00"),
            InlineKeyboardButton(text="۲۰:۰۰", callback_data="adm:dt:time:20:00"),
        ],
    ]
    nav_row = []
    if allow_back:
        nav_row.append(InlineKeyboardButton(text="↩️ تغییر تاریخ", callback_data="adm:dt:back_date"))
    if is_edit:
        nav_row.append(InlineKeyboardButton(text="⏭ بدون تغییر (/skip)", callback_data="adm:dt:skip"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def datetime_end_keyboard(starts_at: datetime, is_edit: bool = False) -> InlineKeyboardMarkup:
    """Build quick duration & end date/time selection keyboard."""
    buttons = [
        [
            InlineKeyboardButton(text="⏱ ۲ ساعت بعد", callback_data="adm:dt:end:2h"),
            InlineKeyboardButton(text="⏱ ۴ ساعت بعد", callback_data="adm:dt:end:4h"),
            InlineKeyboardButton(text="⏱ ۲۴ ساعت بعد", callback_data="adm:dt:end:24h"),
        ],
        [
            InlineKeyboardButton(text="📅 همان روز ۲۳:۵۹", callback_data="adm:dt:end:sameday_end"),
            InlineKeyboardButton(text="📅 ۳ روز بعد", callback_data="adm:dt:end:3d"),
            InlineKeyboardButton(text="📅 ۱ هفته بعد", callback_data="adm:dt:end:7d"),
        ],
        [
            InlineKeyboardButton(text="🗓 انتخاب تاریخ دیگر", callback_data="adm:dt:end:custom_date"),
        ],
    ]
    if is_edit:
        buttons.append([InlineKeyboardButton(text="⏭ بدون تغییر زمان پایان (/skip)", callback_data="adm:dt:skip")])
    buttons.append([InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

