"""
CSV bulk import for parents.

One row per child: a parent with two children appears on two rows with the
same mobile number and gets one account linked to both.
"""

import logging
from typing import Any

from django.db import transaction

from common.csv_import import (
    CSVImportError,
    FIRST_DATA_ROW,
    add_row_error,
    clean_rows,
    merge_errors,
    read_csv_rows,
    validate_rows,
)

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "student_id",
    "name",
    "phone_number",
)

CSV_COLUMNS = REQUIRED_COLUMNS

MAX_ROWS = 1000


def _check_rows_against_each_other(rows: list[dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    """
    Catch clashes inside the file: the same child listed twice for the
    same number, or one number given two different parent names.
    """

    errors: dict[str, dict[str, list[str]]] = {}
    pairs: dict[tuple[str, str], int] = {}
    names: dict[str, tuple[str, int]] = {}

    for index, row in enumerate(rows, start=FIRST_DATA_ROW):
        student_id = row.get("student_id", "").strip().upper()
        phone = row.get("phone_number", "").strip()
        name = " ".join(row.get("name", "").split())

        if not (student_id and phone):
            continue

        first = pairs.setdefault((student_id, phone), index)
        if first != index:
            add_row_error(errors, index, "student_id", f"This student and mobile number are repeated from row {first}.")

        if name:
            seen = names.setdefault(phone, (name, index))
            if seen[0].lower() != name.lower():
                add_row_error(
                    errors,
                    index,
                    "name",
                    f'This mobile number was given as "{seen[0]}" on row {seen[1]}. One number belongs to one parent.',
                )

    return errors


def _resolve_students(*, rows, students_queryset) -> tuple[dict[str, Any], dict[str, dict[str, list[str]]]]:
    """Map each row's student ID to a student the uploader can see."""

    wanted = {row["student_id"].strip().upper() for row in rows if row.get("student_id")}
    found = {s.student_id.upper(): s for s in students_queryset.filter(student_id__in=wanted)}

    errors: dict[str, dict[str, list[str]]] = {}
    for index, row in enumerate(rows, start=FIRST_DATA_ROW):
        student_id = row.get("student_id", "").strip().upper()
        if student_id and student_id not in found:
            add_row_error(errors, index, "student_id", "No student with this ID in your scope.")

    return found, errors


def _check_existing_parents(rows: list[dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    """A mobile number that already signs in as staff cannot become a parent."""

    from accounts.models import User
    from common.choices import UserRole

    phones = {row["phone_number"].strip() for row in rows if row.get("phone_number")}
    taken = set(
        User.objects.filter(phone_number__in=phones)
        .exclude(role=UserRole.PARENT)
        .values_list("phone_number", flat=True)
    )

    errors: dict[str, dict[str, list[str]]] = {}
    for index, row in enumerate(rows, start=FIRST_DATA_ROW):
        if row.get("phone_number", "").strip() in taken:
            add_row_error(errors, index, "phone_number", "This mobile number belongs to a staff account.")

    return errors


@transaction.atomic
def import_parents_from_csv(*, file_obj, students_queryset, row_serializer_class, actor) -> dict[str, Any]:
    """
    Create parents (or link existing ones) for students from a CSV file.

    ``students_queryset`` is everything the uploader may link, already
    narrowed to one school for a Super Admin. The whole file is checked
    before anything is written; any bad row fails the upload and every
    problem is reported at once.
    """

    from .services import create_or_link_parent, find_parent_by_phone

    raw_rows = read_csv_rows(file_obj, required_columns=REQUIRED_COLUMNS, known_columns=CSV_COLUMNS, max_rows=MAX_ROWS)
    rows = clean_rows(raw_rows, known_columns=CSV_COLUMNS)

    validated, field_errors = validate_rows(rows, row_serializer_class=row_serializer_class)
    students, student_errors = _resolve_students(rows=rows, students_queryset=students_queryset)

    errors = merge_errors(
        field_errors,
        student_errors,
        _check_rows_against_each_other(rows),
        _check_existing_parents(rows),
    )

    if errors:
        raise CSVImportError(errors)

    results = []
    for index, data in enumerate(validated, start=FIRST_DATA_ROW):
        student = students[data["student_id"]]
        existing = find_parent_by_phone(data["phone_number"])
        already_linked = existing is not None and existing.students.filter(pk=student.pk).exists()

        parent, created = create_or_link_parent(
            name=data["name"],
            phone_number=data["phone_number"],
            student=student,
            actor=actor,
        )
        results.append(
            {
                "row": index,
                "student_id": student.student_id,
                "student_name": student.name,
                "phone_number": data["phone_number"],
                "parent": parent.pk,
                "created": created,
                "already_linked": already_linked,
            }
        )

    logger.info(
        "Bulk parent upload by user %s: %s row(s), %s new parent(s)",
        actor.pk,
        len(results),
        sum(r["created"] for r in results),
    )

    return {"rows": results, "parent_ids": list(dict.fromkeys(r["parent"] for r in results))}
