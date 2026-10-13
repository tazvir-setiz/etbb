import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class DateTimeParseError(ValueError):
    """Raised when user input cannot be parsed as a valid datetime."""


def digits_to_ascii(value: str) -> str:
    """Convert Persian and Arabic numerals to standard ASCII digits."""
    return value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def to_persian_digits(value: str | int) -> str:
    """Convert ASCII digits to Persian digits."""
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert a Gregorian date (year, month, day) to a Solar Hijri (Jalali) date."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


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


PERSIAN_WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یک‌شنبه"]
PERSIAN_MONTHS = [
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


def _get_tz(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def format_shamsi_date(
    dt: datetime,
    include_weekday: bool = False,
    persian_digits: bool = True,
    timezone_name: str = "Asia/Tehran",
) -> str:
    """Format a datetime into a Solar Hijri (Shamsi) date string."""
    tz = _get_tz(timezone_name)
    local_dt = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    jy, jm, jd = gregorian_to_jalali(local_dt.year, local_dt.month, local_dt.day)
    if include_weekday:
        weekday = PERSIAN_WEEKDAYS[local_dt.weekday()]
        month_name = PERSIAN_MONTHS[jm]
        res = f"{weekday} {jd} {month_name} {jy}"
    else:
        res = f"{jy:04d}/{jm:02d}/{jd:02d}"
    return to_persian_digits(res) if persian_digits else res


def format_shamsi_datetime(
    dt: datetime,
    include_weekday: bool = True,
    persian_digits: bool = True,
    timezone_name: str = "Asia/Tehran",
) -> str:
    """Format a datetime into a friendly Solar Hijri (Shamsi) datetime string."""
    tz = _get_tz(timezone_name)
    local_dt = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    jy, jm, jd = gregorian_to_jalali(local_dt.year, local_dt.month, local_dt.day)
    time_part = f"{local_dt.hour:02d}:{local_dt.minute:02d}"
    if include_weekday:
        weekday = PERSIAN_WEEKDAYS[local_dt.weekday()]
        month_name = PERSIAN_MONTHS[jm]
        res = f"{weekday} {jd} {month_name} {jy} — ساعت {time_part}"
    else:
        res = f"{jy:04d}/{jm:02d}/{jd:02d} {time_part}"
    return to_persian_digits(res) if persian_digits else res


def get_system_time_info(timezone_name: str = "Asia/Tehran") -> tuple[datetime, str]:
    """Return the current localized datetime and a formatted display string."""
    tz = _get_tz(timezone_name)
    now = datetime.now(tz)
    formatted = format_shamsi_datetime(now, include_weekday=True, persian_digits=True, timezone_name=timezone_name)
    header = f"🕒 زمان کنونی سیستم (به وقت ایران):\n📅 {formatted}"
    return now, header


def parse_time_components(value: str) -> tuple[int, int]:
    """Parse a time string (e.g. '09:30', '9', '۱۴:۱۵') into (hour, minute)."""
    clean = digits_to_ascii(value.strip())
    match = re.match(r"^(\d{1,2})(?::(\d{1,2}))?$", clean)
    if not match:
        raise DateTimeParseError("ساعت نامعتبر است. نمونه مجاز: ۰۹:۰۰ یا ۱۴:۳۰")
    hh, mm = match.groups()
    hour = int(hh)
    minute = int(mm) if mm is not None else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise DateTimeParseError("ساعت باید در بازهٔ ۰۰:۰۰ تا ۲۳:۵۹ باشد.")
    return hour, minute


def parse_date_components(value: str) -> tuple[int, int, int]:
    """Parse a date string (e.g. '1405/07/21', '2026-10-13') into Gregorian (gy, gm, gd)."""
    clean = digits_to_ascii(value.strip())
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", clean)
    if not match:
        raise DateTimeParseError("تاریخ نامعتبر است. نمونه مجاز: ۱۴۰۵/۰۷/۲۱")
    y, m, d = (int(x) for x in match.groups())
    if 1300 <= y < 1500:
        return jalali_to_gregorian(y, m, d)
    try:
        dt = datetime(y, m, d)
        return dt.year, dt.month, dt.day
    except ValueError as exc:
        raise DateTimeParseError(f"تاریخ نامعتبر است: {exc}") from exc


def parse_flexible_datetime(
    value: str,
    timezone_name: str = "Asia/Tehran",
    base_date: datetime | None = None,
    pending_date: tuple[int, int, int] | None = None,
) -> tuple[datetime | None, tuple[int, int, int] | None]:
    """Parse user input which may be a full datetime, date only, or time only.

    Returns:
        (datetime_obj, None) if full datetime was resolved.
        (None, (gy, gm, gd)) if only a date was provided and time is still needed.
    """
    raw = value.strip()
    clean = digits_to_ascii(raw)
    if not clean:
        raise DateTimeParseError("ورودی نباید خالی باشد.")

    tz = _get_tz(timezone_name)
    now = datetime.now(tz)

    # Relative keyword shortcuts
    lower_raw = raw.lower()
    if lower_raw == "امروز":
        return None, (now.year, now.month, now.day)
    if lower_raw == "فردا":
        tomorrow = now + timedelta(days=1)
        return None, (tomorrow.year, tomorrow.month, tomorrow.day)
    if lower_raw in ("پس‌فردا", "پس فردا"):
        day_after = now + timedelta(days=2)
        return None, (day_after.year, day_after.month, day_after.day)

    # 1. Full datetime pattern: YYYY[-/]MM[-/]DD [T] HH:MM[:SS]
    pattern_full = r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T\s](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)$"
    match_full = re.match(pattern_full, clean)
    if match_full:
        y, m, d, hh, mm, ss = match_full.groups()
        year, month, day = int(y), int(m), int(d)
        hour = int(hh)
        minute = int(mm)
        second = int(ss) if ss is not None else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            raise DateTimeParseError("ساعت باید در بازهٔ ۰۰:۰۰ تا ۲۳:۵۹ باشد.")
        if 1300 <= year < 1500:
            gy, gm, gd = jalali_to_gregorian(year, month, day)
            dt = datetime(gy, gm, gd, hour, minute, second, tzinfo=tz)
        else:
            try:
                dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)
            except ValueError as exc:
                raise DateTimeParseError(f"تاریخ نامعتبر است: {exc}") from exc
        return dt, None

    # 2. Date only pattern: YYYY[-/]MM[-/]DD
    pattern_date = r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$"
    match_date = re.match(pattern_date, clean)
    if match_date:
        y, m, d = (int(x) for x in match_date.groups())
        if 1300 <= y < 1500:
            gy, gm, gd = jalali_to_gregorian(y, m, d)
        else:
            try:
                datetime(y, m, d)
                gy, gm, gd = y, m, d
            except ValueError as exc:
                raise DateTimeParseError(f"تاریخ نامعتبر است: {exc}") from exc
        return None, (gy, gm, gd)

    # 3. Time only pattern: HH:MM or HH (digits with colon or 1-2 digits)
    pattern_time = r"^(\d{1,2})(?::(\d{1,2}))?$"
    match_time = re.match(pattern_time, clean)
    if match_time and (":" in clean or len(clean) <= 2):
        hour, minute = parse_time_components(clean)
        # Case A: pending_date was selected earlier
        if pending_date is not None:
            py, pm, pd = pending_date
            return datetime(py, pm, pd, hour, minute, tzinfo=tz), None
        # Case B: base_date exists (e.g. setting ends_at relative to starts_at)
        if base_date is not None:
            cand = datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=tz)
            if cand <= base_date:
                cand += timedelta(days=1)
            return cand, None
        # Case C: start time with no date provided - use today if in future, else tomorrow
        cand_today = datetime(now.year, now.month, now.day, hour, minute, tzinfo=tz)
        if cand_today > now:
            return cand_today, None
        cand_tomorrow = cand_today + timedelta(days=1)
        return cand_tomorrow, None

    # Fallback to standard ISO parser
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt, None
    except ValueError as exc:
        raise DateTimeParseError(
            "قالب زمان نامعتبر است. نمونه‌های مجاز:\n"
            "• تاریخ و ساعت: ۱۴۰۵/۰۷/۲۱ ۰۹:۰۰\n"
            "• فقط تاریخ: ۱۴۰۵/۰۷/۲۱\n"
            "• فقط ساعت: ۰۹:۰۰ یا ۱۴:۳۰"
        ) from exc


def parse_user_datetime(
    value: str,
    timezone_name: str = "Asia/Tehran",
    base_date: datetime | None = None,
) -> datetime:
    """Parse user input in Gregorian or Persian Shamsi format into an aware datetime."""
    dt, pending = parse_flexible_datetime(value, timezone_name=timezone_name, base_date=base_date)
    if dt is not None:
        return dt
    if pending is not None:
        # Date only was passed: default to 00:00:00
        tz = _get_tz(timezone_name)
        gy, gm, gd = pending
        return datetime(gy, gm, gd, 0, 0, 0, tzinfo=tz)
    raise DateTimeParseError("زمان معتبر نیست.")
