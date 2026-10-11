from io import BytesIO
import pytest
from openpyxl import Workbook

from app.services.people_import import PeopleImportError, parse_people_file


def test_parse_people_file_csv_success():
    csv_content = (
        "شناسه داخلی,نام,نام خانوادگی,توضیح\n"
        "EMP-01,رضا,احمدی,برنامه‌نویس\n"
        "EMP-02,سارا,محمدی,\n"
    ).encode("utf-8-sig")

    records = parse_people_file("people.csv", csv_content)
    assert len(records) == 2
    assert records[0]["internal_id"] == "EMP-01"
    assert records[0]["first_name"] == "رضا"
    assert records[0]["last_name"] == "احمدی"
    assert records[0]["description"] == "برنامه‌نویس"
    assert records[0]["error"] is None

    assert records[1]["internal_id"] == "EMP-02"
    assert records[1]["first_name"] == "سارا"
    assert records[1]["last_name"] == "محمدی"
    assert records[1]["description"] is None
    assert records[1]["error"] is None


def test_parse_people_file_xlsx_success():
    wb = Workbook()
    ws = wb.active
    ws.append(["internal_id", "first_name", "last_name", "description"])
    ws.append(["EMP-10", "مریم", "کریمی", "مدیر"])
    
    stream = BytesIO()
    wb.save(stream)
    xlsx_bytes = stream.getvalue()

    records = parse_people_file("people.xlsx", xlsx_bytes)
    assert len(records) == 1
    assert records[0]["internal_id"] == "EMP-10"
    assert records[0]["first_name"] == "مریم"
    assert records[0]["last_name"] == "کریمی"
    assert records[0]["description"] == "مدیر"
    assert records[0]["error"] is None


def test_parse_people_file_missing_headers():
    csv_content = "نام,توضیح\nرضا,توضیح".encode("utf-8")
    with pytest.raises(PeopleImportError, match="ستون‌های الزامی"):
        parse_people_file("people.csv", csv_content)


def test_parse_people_file_invalid_row():
    csv_content = (
        "شناسه داخلی,نام,نام خانوادگی,توضیح\n"
        ",,احمدی,\n"
    ).encode("utf-8")
    records = parse_people_file("people.csv", csv_content)
    assert len(records) == 1
    assert records[0]["error"] is not None
    assert "شناسهٔ داخلی" in records[0]["error"]
    assert "نام" in records[0]["error"]


def test_parse_people_file_unsupported_format():
    with pytest.raises(PeopleImportError, match="فقط فایل CSV یا XLSX"):
        parse_people_file("people.txt", b"hello")
