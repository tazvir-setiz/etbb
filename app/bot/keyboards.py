from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def participant_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📝 نظرسنجی‌های فعال"), KeyboardButton(text="📊 امتیازهای من")],
        [KeyboardButton(text="ℹ️ راهنما")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="↩️ بازگشت به پنل مدیر")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 مدیریت افراد"), KeyboardButton(text="➕ افزودن فرد")],
            [KeyboardButton(text="🗳 مدیریت نظرسنجی‌ها"), KeyboardButton(text="➕ ساخت نظرسنجی")],
            [KeyboardButton(text="📈 گزارش‌ها"), KeyboardButton(text="🎭 حالت ارزیاب")],
        ],
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
