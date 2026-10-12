"""
CSV bulk import for students.

The class-section comes from the request, not the file, so a CSV cannot
place students somewhere the uploader does not administer. Profile images
are uploaded per student afterwards; a CSV carries no files.
"""

import logging
from typing import Any

from django.db import transaction

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

from .models import Student

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "student_id",
    "name",
    "roll_number",
)

CSV_COLUMNS = REQUIRED_COLUMNS

MAX_ROWS = 1000

UNIQUE_FIELDS = {
    "student_id": lambda value: value.strip().upper(),
    "roll_number": lambda value: value.strip(),
}

UNIQUE_FIELD_LABELS = {
    "student_id": "Student ID",
    "roll_number": "Roll number",
}


def find_existing_conflicts(
    *,
    school_id: int,
    class_section_id: int,
    rows: list[dict[str, str]],
) -> dict[str, dict[str, list[str]]]:
    """
    Report rows clashing with students already in the database.

    Student IDs are checked across the whole school; roll numbers only
    within the destination class-section, matching the two uniqueness
    rules on the model.
    """

    errors: dict[str, dict[str, list[str]]] = {}

    student_ids = [
        row["student_id"].upper()
        for row in rows
        if row.get("student_id")
    ]
    roll_numbers = [
        row["roll_number"].strip()
        for row in rows
        if row.get("roll_number")
    ]

    taken_student_ids = set(
        Student.objects.filter(
            school_id=school_id,
            student_id__in=student_ids,
        ).values_list("student_id", flat=True)
    )

    taken_roll_numbers = set(
        Student.objects.filter(
            class_section_id=class_section_id,
            roll_number__in=roll_numbers,
        ).values_list("roll_number", flat=True)
    )

    for index, row in enumerate(rows, start=FIRST_DATA_ROW):
        student_id = row.get("student_id", "").upper()
        roll_number = row.get("roll_number", "").strip()

        if student_id and student_id in taken_student_ids:
            add_row_error(
                errors,
                index,
                "student_id",
                "A student with this student ID already exists in "
                "this school.",
            )

        if roll_number and roll_number in taken_roll_numbers:
            add_row_error(
                errors,
                index,
                "roll_number",
                "A student with this roll number already exists in "
                "this class section.",
            )

    return errors


@transaction.atomic
def import_students_from_csv(
    *,
    class_section,
    file_obj,
    row_serializer_class,
) -> dict[str, Any]:
    """
    Enrol students into one class-section from a CSV file.

    The whole file is validated before anything is written: if any row
    is bad, nothing is created and every problem is reported at once.
    A partial import would leave a teacher guessing which half of their
    class list landed.
    """

    from .services import create_student

    school = class_section.academic_year.school

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
            class_section_id=class_section.id,
            rows=rows,
        ),
    )

    if errors:
        raise CSVImportError(errors)

    created = [
        create_student(
            class_section=class_section,
            validated_data=validated_data,
        )
        for validated_data in cleaned_rows
    ]

    logger.info(
        "Imported %s students into class section %s",
        len(created),
        class_section.id,
    )

    return {
        "created": len(created),
        "students": created,
    }
