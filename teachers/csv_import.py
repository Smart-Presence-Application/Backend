"""
CSV bulk import for teachers.

UNIQUE_FIELDS says what counts as "the same value" when looking for
repeats within a file.
"""

import logging
from typing import Any

from django.db import transaction

from accounts.models import User
from common.csv_import import (
    CSVImportError,
    FIRST_DATA_ROW,
    add_row_error,
    clean_rows,
    find_duplicates_within_file,
    merge_errors,
    read_csv_rows,
    validate_rows,
)

from .selectors import get_existing_employee_ids

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "employee_id",
    "name",
    "email",
)

OPTIONAL_COLUMNS = (
    "phone_number",
    "gender",
    "address",
    "city",
    "state",
    "country",
    "pincode",
    "joining_date",
)

CSV_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

MAX_ROWS = 1000

UNIQUE_FIELDS = {
    "email": lambda value: value.strip().lower(),
    "employee_id": lambda value: value.strip().upper(),
}

UNIQUE_FIELD_LABELS = {
    "email": "Email",
    "employee_id": "Employee ID",
}


def find_existing_conflicts(
    *,
    school_id: int,
    rows: list[dict[str, str]],
) -> dict[str, dict[str, list[str]]]:
    """Report rows clashing with records already in the database."""

    errors: dict[str, dict[str, list[str]]] = {}

    emails = [
        row["email"]
        for row in rows
        if row.get("email")
    ]
    employee_ids = [
        row["employee_id"].upper()
        for row in rows
        if row.get("employee_id")
    ]

    taken_emails = {
        email.lower()
        for email in User.objects.filter(
            email__in=emails,
        ).values_list("email", flat=True)
    }

    taken_employee_ids = get_existing_employee_ids(
        school_id=school_id,
        employee_ids=employee_ids,
    )

    for index, row in enumerate(rows, start=FIRST_DATA_ROW):
        email = row.get("email", "").lower()
        employee_id = row.get("employee_id", "").upper()

        if email and email in taken_emails:
            add_row_error(
                errors,
                index,
                "email",
                "A user with this email already exists.",
            )

        if employee_id and employee_id in taken_employee_ids:
            add_row_error(
                errors,
                index,
                "employee_id",
                "A teacher with this employee ID already exists "
                "in this school.",
            )

    return errors


@transaction.atomic
def import_teachers_from_csv(
    *,
    school,
    file_obj,
    row_serializer_class,
) -> dict[str, Any]:
    """
    Create teachers from a CSV file.

    The whole file is validated before anything is written: if any row
    is bad, nothing is created and every problem is reported at once.
    A partial import would leave an administrator guessing which half
    of their spreadsheet landed.
    """

    from .services import create_teacher

    raw_rows = read_csv_rows(
        file_obj,
        required_columns=REQUIRED_COLUMNS,
        known_columns=CSV_COLUMNS,
        max_rows=MAX_ROWS,
    )

    rows = clean_rows(raw_rows, known_columns=CSV_COLUMNS)

    cleaned_rows, field_errors = validate_rows(
        rows,
        row_serializer_class=row_serializer_class,
    )

    errors = merge_errors(
        field_errors,
        find_duplicates_within_file(
            rows,
            unique_fields=UNIQUE_FIELDS,
            labels=UNIQUE_FIELD_LABELS,
        ),
        find_existing_conflicts(
            school_id=school.id,
            rows=rows,
        ),
    )

    if errors:
        raise CSVImportError(errors)

    created = [
        create_teacher(
            school=school,
            validated_data=validated_data,
        )
        for validated_data in cleaned_rows
    ]

    logger.info(
        "Imported %s teachers into school %s",
        len(created),
        school.id,
    )

    return {
        "created": len(created),
        "teachers": created,
    }
