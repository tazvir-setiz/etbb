from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from app.services.datetime_parser import (
    DateTimeParseError,
    digits_to_ascii,
    format_shamsi_date,
    format_shamsi_datetime,
    get_system_time_info,
    gregorian_to_jalali,
    jalali_to_gregorian,
    parse_date_components,
    parse_flexible_datetime,
    parse_time_components,
    parse_user_datetime,
    to_persian_digits,
)


def test_digits_to_ascii():
    assert digits_to_ascii("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert digits_to_ascii("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert digits_to_ascii("2026-10-11") == "2026-10-11"


def test_to_persian_digits():
    assert to_persian_digits("0123456789") == "۰۱۲۳۴۵۶۷۸۹"
    assert to_persian_digits("1405/07/21 09:30") == "۱۴۰۵/۰۷/۲۱ ۰۹:۳۰"


def test_jalali_to_gregorian():
    # 1405-07-19 is 2026-10-11
    gy, gm, gd = jalali_to_gregorian(1405, 7, 19)
    assert (gy, gm, gd) == (2026, 10, 11)

    # 1403-01-01 is 2024-03-20
    gy, gm, gd = jalali_to_gregorian(1403, 1, 1)
    assert (gy, gm, gd) == (2024, 3, 20)

    with pytest.raises(DateTimeParseError, match="ماه شمسی نامعتبر"):
        jalali_to_gregorian(1405, 13, 1)

    with pytest.raises(DateTimeParseError, match="روز شمسی نامعتبر"):
        jalali_to_gregorian(1405, 7, 32)


def test_gregorian_to_jalali():
    assert gregorian_to_jalali(2026, 10, 11) == (1405, 7, 19)
    assert gregorian_to_jalali(2026, 10, 13) == (1405, 7, 21)
    assert gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1)


def test_format_shamsi_formatting():
    tz = ZoneInfo("Asia/Tehran")
    dt = datetime(2026, 10, 13, 9, 30, tzinfo=tz)

    date_str = format_shamsi_date(dt, include_weekday=False, persian_digits=True)
    assert date_str == "۱۴۰۵/۰۷/۲۱"

    date_with_weekday = format_shamsi_date(dt, include_weekday=True, persian_digits=True)
    assert "سه‌شنبه" in date_with_weekday
    assert "مهر" in date_with_weekday
    assert "۱۴۰۵" in date_with_weekday

    dt_str = format_shamsi_datetime(dt, include_weekday=True, persian_digits=True)
    assert "سه‌شنبه" in dt_str
    assert "۰۹:۳۰" in dt_str


def test_get_system_time_info():
    now, header = get_system_time_info("Asia/Tehran")
    assert now.tzinfo is not None
    assert "زمان کنونی سیستم" in header
    assert "🕒" in header
    assert "📅" in header


def test_parse_time_components():
    assert parse_time_components("09:30") == (9, 30)
    assert parse_time_components("۹:۳۰") == (9, 30)
    assert parse_time_components("14:00") == (14, 0)
    assert parse_time_components("۱۴") == (14, 0)

    with pytest.raises(DateTimeParseError):
        parse_time_components("25:00")
    with pytest.raises(DateTimeParseError):
        parse_time_components("10:60")


def test_parse_date_components():
    assert parse_date_components("1405/07/21") == (2026, 10, 13)
    assert parse_date_components("۱۴۰۵-۰۷-۲۱") == (2026, 10, 13)
    assert parse_date_components("2026-10-13") == (2026, 10, 13)


def test_parse_flexible_datetime():
    # 1. Full datetime
    dt, pending = parse_flexible_datetime("۱۴۰۵/۰۷/۲۱ ۰۹:۳۰", "Asia/Tehran")
    assert dt is not None
    assert pending is None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 10, 13, 9, 30)

    # 2. Date only
    dt2, pending2 = parse_flexible_datetime("۱۴۰۵/۰۷/۲۱", "Asia/Tehran")
    assert dt2 is None
    assert pending2 == (2026, 10, 13)

    # 3. Time only with pending date
    dt3, pending3 = parse_flexible_datetime("14:15", "Asia/Tehran", pending_date=(2026, 10, 13))
    assert dt3 is not None
    assert pending3 is None
    assert (dt3.year, dt3.month, dt3.day, dt3.hour, dt3.minute) == (2026, 10, 13, 14, 15)

    # 4. Time only relative to base_date
    tz = ZoneInfo("Asia/Tehran")
    base = datetime(2026, 10, 13, 10, 0, tzinfo=tz)
    # Time after base hour on same day
    dt4, _ = parse_flexible_datetime("14:00", "Asia/Tehran", base_date=base)
    assert dt4.day == 13
    assert dt4.hour == 14

    # Time before base hour on same day -> moves to next day
    dt5, _ = parse_flexible_datetime("08:00", "Asia/Tehran", base_date=base)
    assert dt5.day == 14
    assert dt5.hour == 8

    # 5. Keywords
    _, pending_today = parse_flexible_datetime("امروز", "Asia/Tehran")
    assert pending_today is not None
    _, pending_tomorrow = parse_flexible_datetime("فردا", "Asia/Tehran")
    assert pending_tomorrow is not None
    _, pending_dayafter = parse_flexible_datetime("پس‌فردا", "Asia/Tehran")
    assert pending_dayafter is not None


def test_parse_user_datetime_persian_solar():
    dt = parse_user_datetime("1405/07/19 09:30", "Asia/Tehran")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 11
    assert dt.hour == 9
    assert dt.minute == 30
    assert dt.tzinfo == ZoneInfo("Asia/Tehran")

    # With Persian digits
    dt2 = parse_user_datetime("۱۴۰۵-۰۷-۱۹ ۰۹:۳۰:۰۰", "Asia/Tehran")
    assert dt2.year == 2026
    assert dt2.month == 10
    assert dt2.day == 11
    assert dt2.hour == 9
    assert dt2.minute == 30
    assert dt2.second == 0


def test_parse_user_datetime_gregorian():
    dt = parse_user_datetime("2026-10-15 14:00", "Asia/Tehran")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 15
    assert dt.hour == 14
    assert dt.minute == 0
    assert dt.tzinfo == ZoneInfo("Asia/Tehran")

    dt_iso = parse_user_datetime("2026-10-15T14:00:00", "Asia/Tehran")
    assert dt_iso == dt


def test_parse_user_datetime_invalid():
    with pytest.raises(DateTimeParseError):
        parse_user_datetime("")

    with pytest.raises(DateTimeParseError):
        parse_user_datetime("not-a-date")

    with pytest.raises(DateTimeParseError, match="ساعت باید در بازه"):
        parse_user_datetime("2026-10-15 25:00")
