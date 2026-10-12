"""Turn report sheets into a styled .xlsx workbook."""

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from typing import Any, Iterable

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="2563EB")
MIN_WIDTH = 8
MAX_WIDTH = 50


@dataclass
class Sheet:
    title: str
    columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)


def cell_value(value: Any) -> Any:
    """
    Excel cannot hold timezone-aware datetimes, so they are shown in the
    server's local time. Booleans read better as Yes/No.
    """

    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.replace(tzinfo=None, microsecond=0)

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if value is None:
        return ""

    return value


def number_format(value: Any) -> str | None:
    if isinstance(value, datetime):
        return "yyyy-mm-dd hh:mm"

    if isinstance(value, date):
        return "yyyy-mm-dd"

    return None


def display_width(value: Any) -> int:
    if isinstance(value, datetime):
        return 16

    if isinstance(value, date):
        return 10

    return len(str(value))


def build_workbook(sheets: Iterable[Sheet]) -> bytes:
    """Render the sheets as .xlsx bytes, truncating titles to Excel's 31 characters."""

    workbook = Workbook()
    workbook.remove(workbook.active)

    for sheet in sheets:
        worksheet = workbook.create_sheet(sheet.title[:31])
        worksheet.append(sheet.columns)

        for cell in worksheet[1]:
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(vertical="center")

        widths = [len(column) for column in sheet.columns]

        for row in sheet.rows:
            values = [cell_value(value) for value in row]
            worksheet.append(values)

            for index, value in enumerate(values):
                widths[index] = max(widths[index], display_width(value))

                fmt = number_format(value)

                if fmt:
                    worksheet.cell(row=worksheet.max_row, column=index + 1).number_format = fmt

        for index, width in enumerate(widths, start=1):
            worksheet.column_dimensions[get_column_letter(index)].width = min(
                max(width + 2, MIN_WIDTH),
                MAX_WIDTH,
            )

        worksheet.freeze_panes = "A2"

        if sheet.rows:
            worksheet.auto_filter.ref = worksheet.dimensions

    buffer = BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


def xlsx_response(filename: str, sheets: Iterable[Sheet]) -> HttpResponse:
    response = HttpResponse(build_workbook(sheets), content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response
