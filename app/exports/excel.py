from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Person, Survey, User, Vote


async def build_survey_workbook(session: AsyncSession, survey_id: int) -> BytesIO:
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise ValueError("نظرسنجی پیدا نشد.")
    votes = await session.execute(
        select(Vote, Person.display_name, User.full_name, User.platform_user_id)
        .join(Person, Person.id == Vote.person_id)
        .join(User, User.id == Vote.user_id)
        .where(Vote.survey_id == survey_id)
        .order_by(Person.display_name, Vote.created_at)
    )
    workbook = Workbook()
    summary = workbook.active
    summary.title = "خلاصه"
    summary.append(["فرد", "تعداد امتیاز", "میانگین"])
    detail = workbook.create_sheet("امتیازها")
    detail.append(["فرد", "امتیاز", "نظر", "زمان ثبت"] + ([] if survey.anonymous else ["رأی‌دهنده", "شناسه کاربر", "پیام‌رسان"]))
    grouped: dict[str, list[int]] = {}
    for vote, person_name, voter_name, voter_id in votes:
        grouped.setdefault(person_name, []).append(vote.score)
        record: list[object] = [person_name, vote.score, vote.comment or "", vote.created_at]
        if not survey.anonymous:
            record.extend([voter_name, voter_id, vote.user.platform])
        detail.append(record)
    for name, scores in sorted(grouped.items()):
        summary.append([name, len(scores), sum(scores) / len(scores)])
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="right")
        for column in sheet.columns:
            letter = column[0].column_letter
            sheet.column_dimensions[letter].width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 12), 32)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output
