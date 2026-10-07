from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="📝 نظرسنجی‌های فعال"), KeyboardButton(text="📊 امتیازهای من")],
            [KeyboardButton(text="ℹ️ راهنما")]]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ پنل مدیریت")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def inline_options(items: list[tuple[str, str]], columns: int = 1) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=label, callback_data=data) for label, data in items]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + columns] for i in range(0, len(buttons), columns)])
