from zoneinfo import ZoneInfo
import pytest

from app.services.datetime_parser import (
    DateTimeParseError,
    digits_to_ascii,
    jalali_to_gregorian,
    parse_user_datetime,
)


def test_digits_to_ascii():
    assert digits_to_ascii("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert digits_to_ascii("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert digits_to_ascii("2026-10-11") == "2026-10-11"


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
