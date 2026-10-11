import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class DateTimeParseError(ValueError):
    """Raised when user input cannot be parsed as a valid datetime."""


def digits_to_ascii(value: str) -> str:
    """Convert Persian and Arabic numerals to standard ASCII digits."""
    return value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Convert a Solar Hijri (Jalali) date to a Gregorian date."""
    if not (1 <= jm <= 12):
        raise DateTimeParseError(f"ماه شمسی نامعتبر است: {jm}")
    max_days = 31 if jm <= 6 else 30
    if jd < 1 or jd > max_days:
        raise DateTimeParseError(f"روز شمسی نامعتبر است: {jd}")

    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += ((jm - 7) * 30) + 186

    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        days -= 1
        gy += days // 365
        days %= 365

    sal_a = [
        0,
        31,
        29 if ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]
    gm = 0
    while gm < 12 and days >= sal_a[gm + 1]:
        days -= sal_a[gm + 1]
        gm += 1
    return gy, gm + 1, days + 1


def parse_user_datetime(value: str, timezone_name: str = "Asia/Tehran") -> datetime:
    """Parse user input in Gregorian or Persian Shamsi format into an aware datetime."""
    clean = digits_to_ascii(value.strip())
    if not clean:
        raise DateTimeParseError("زمان نباید خالی باشد.")

    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")

    # Regular expression matching YYYY[-/]MM[-/]DD [T] HH:MM[:SS]
    pattern = r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T\s](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$"
    match = re.match(pattern, clean)
    if match:
        y, m, d, hh, mm, ss = match.groups()
        year, month, day = int(y), int(m), int(d)
        hour = int(hh) if hh is not None else 0
        minute = int(mm) if mm is not None else 0
        second = int(ss) if ss is not None else 0

        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            raise DateTimeParseError("ساعت باید در بازهٔ ۰۰:۰۰ تا ۲۳:۵۹ باشد.")

        # Check if year is Jalali (1300 to 1499)
        if 1300 <= year < 1500:
            gy, gm, gd = jalali_to_gregorian(year, month, day)
            dt = datetime(gy, gm, gd, hour, minute, second)
        else:
            try:
                dt = datetime(year, month, day, hour, minute, second)
            except ValueError as exc:
                raise DateTimeParseError(f"تاریخ نامعتبر است: {exc}") from exc

        return dt.replace(tzinfo=tz)

    # Fallback to standard ISO parser
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt
    except ValueError as exc:
        raise DateTimeParseError(
            "قالب زمان نامعتبر است. نمونه‌های مجاز: "
            "۱۴۰۵/۰۷/۲۰ ۰۹:۰۰ یا 2026-10-15 09:00"
        ) from exc
