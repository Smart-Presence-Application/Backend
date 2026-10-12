"""Shared CSV bulk-import machinery.

Reading, validating and error-reporting are the same whatever the rows
describe. Each app supplies its own column list, its own row serializer
and its own clash lookups, and keeps the generic parts from here.

Rows are numbered the way a spreadsheet numbers them, so the header is
row 1 and the first record is row 2 (FIRST_DATA_ROW).
"""

import codecs
import csv
from typing import Any, Callable, Iterable

FIRST_DATA_ROW = 2

DEFAULT_MAX_ROWS = 1000


class CSVImportError(Exception):
    """
    Raised when a CSV cannot be imported.

    ``errors`` maps a row number (or "file") to the problems found
    there, so the caller can report every bad row at once. Row numbers
    are strings because they share the mapping with the "file" key and
    because JSON object keys are strings either way.
    """

    def __init__(self, errors: dict[Any, Any]):
        self.errors = errors
        super().__init__("CSV validation failed.")


def file_error(message: str) -> CSVImportError:
    return CSVImportError({"file": [message]})


def normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_")


def add_row_error(
    errors: dict[str, dict[str, list[str]]],
    row_number: int,
    field: str,
    message: str,
) -> None:
    errors.setdefault(str(row_number), {}).setdefault(
        field, []
    ).append(message)


def merge_errors(*error_maps) -> dict[Any, Any]:
    merged: dict[Any, Any] = {}

    for error_map in error_maps:
        for key, value in error_map.items():
            if key not in merged:
                merged[key] = dict(value)
                continue

            for field, messages in value.items():
                merged[key].setdefault(field, []).extend(messages)

    return merged


def read_csv_rows(
    file_obj,
    *,
    required_columns: Iterable[str],
    known_columns: Iterable[str],
    max_rows: int = DEFAULT_MAX_ROWS,
) -> list[dict[str, str]]:
    """
    Decode an uploaded CSV into a list of column-keyed rows.

    Headers are matched case-insensitively and with spaces treated as
    underscores, so "Student ID" and "student_id" are the same column.
    """

    required_columns = tuple(required_columns)
    known_columns = tuple(known_columns)

    file_obj.seek(0)

    reader = csv.DictReader(
        codecs.iterdecode(file_obj, "utf-8-sig"),
    )

    try:
        fieldnames = reader.fieldnames
    except (csv.Error, UnicodeDecodeError) as exc:
        raise file_error(f"The CSV file could not be read: {exc}")

    if not fieldnames:
        raise file_error("The CSV file is empty.")

    reader.fieldnames = [
        normalize_header(name)
        for name in fieldnames
    ]

    missing = [
        column
        for column in required_columns
        if column not in reader.fieldnames
    ]

    if missing:
        raise file_error(
            "Missing required column(s): "
            + ", ".join(missing)
            + ". Expected columns: "
            + ", ".join(known_columns)
            + "."
        )

    try:
        rows = list(reader)
    except (csv.Error, UnicodeDecodeError) as exc:
        raise file_error(f"The CSV file could not be read: {exc}")

    if not rows:
        raise file_error("The CSV file contains no data rows.")

    if len(rows) > max_rows:
        raise file_error(
            f"The CSV file contains {len(rows)} rows, which is more "
            f"than the {max_rows}-row limit."
        )

    return rows


def clean_rows(
    rows: list[dict[str, str]],
    *,
    known_columns: Iterable[str],
) -> list[dict[str, str]]:
    """Keep only known columns, trimmed, dropping blanks."""

    known_columns = tuple(known_columns)

    cleaned = []

    for row in rows:
        kept = {}

        for column in known_columns:
            value = (row.get(column) or "").strip()

            if value:
                kept[column] = value

        cleaned.append(kept)

    return cleaned


def find_duplicates_within_file(
    rows: list[dict[str, str]],
    *,
    unique_fields: dict[str, Callable[[str], str]],
    labels: dict[str, str] | None = None,
) -> dict[str, dict[str, list[str]]]:
    """
    Report rows that repeat a value seen earlier in the same file.

    ``unique_fields`` maps a column to the normaliser that decides what
    counts as the same value, so casing differences do not slip past.

    A file that collides with itself would otherwise fail halfway
    through with a database error naming only the second row.
    """

    labels = labels or {}

    errors: dict[str, dict[str, list[str]]] = {}
    seen: dict[str, dict[str, int]] = {
        field: {} for field in unique_fields
    }

    for index, row in enumerate(rows, start=FIRST_DATA_ROW):
        for field, normalize in unique_fields.items():
            raw = row.get(field)

            if not raw:
                continue

            value = normalize(raw)
            previous = seen[field].get(value)

            if previous is not None:
                add_row_error(
                    errors,
                    index,
                    field,
                    f"{labels.get(field, 'Value')} duplicated in this "
                    f"file, first seen on row {previous}.",
                )
            else:
                seen[field][value] = index

    return errors


def validate_rows(
    rows: list[dict[str, str]],
    *,
    row_serializer_class,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Run each row through a serializer.

    Returns the validated rows (with ``None`` in place of any that
    failed) alongside the per-row error map.
    """

    errors: dict[str, Any] = {}
    validated: list[Any] = []

    for index, row in enumerate(rows, start=FIRST_DATA_ROW):
        serializer = row_serializer_class(data=row)

        if serializer.is_valid():
            validated.append(serializer.validated_data)
            continue

        validated.append(None)
        errors[str(index)] = serializer.errors

    return validated, errors
