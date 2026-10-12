"""
Academic business logic.

A holiday and a working-day record marked HOLIDAY describe the same fact
from two sides, so every write on either side mirrors itself on the other.
The sync helpers write through the ORM directly, never through the
create_*/update_* services, so the mirroring cannot recurse.
"""
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from common.choices import DayType, Weekday

from .models import (
AcademicYear,
ClassSection,
Holiday,
SchoolClass,
Section,
WorkingDay,
)
from .selectors import get_working_days_for_dates
from .validators import (
    validate_academic_year_dates,
    validate_academic_year_overlap,
    validate_academic_year_school,
    validate_authorized_school,
    validate_date_in_academic_year,
    validate_same_school,
    validate_school_ownership,
)

@transaction.atomic
def create_academic_year(
*,
school,
validated_data: dict[str, Any],
) -> AcademicYear:
    """
    Create an academic year for a school.

    Academic-year date ranges must not overlap with another academic
    year belonging to the same school.
    """

    validate_academic_year_overlap(
        school_id=school.id,
        start_date=validated_data["start_date"],
        end_date=validated_data["end_date"],
    )

    academic_year = AcademicYear(
        school=school,
        **validated_data,
    )

    academic_year.full_clean()

    academic_year.save()

    return academic_year


@transaction.atomic
def update_academic_year(
*,
academic_year: AcademicYear,
validated_data: dict[str, Any],
) -> AcademicYear:
    """Update an academic year while preventing date-range overlap."""


    start_date = validated_data.get(
        "start_date",
        academic_year.start_date,
    )
    end_date = validated_data.get(
        "end_date",
        academic_year.end_date,
    )

    validate_academic_year_overlap(
        school_id=academic_year.school_id,
        start_date=start_date,
        end_date=end_date,
        instance=academic_year,
    )

    for field, value in validated_data.items():
        setattr(academic_year, field, value)
        
    academic_year.full_clean()

    academic_year.save(
        update_fields=[
            *validated_data.keys(),
            "updated_at",
        ],
    )

    return academic_year


@transaction.atomic
def activate_academic_year(
    *,
    academic_year: AcademicYear,
) -> AcademicYear:
    academic_year = (
        AcademicYear.objects
        .select_for_update()
        .get(pk=academic_year.pk)
    )

    (
        AcademicYear.objects
        .select_for_update()
        .filter(
            school_id=academic_year.school_id,
            is_active=True,
        )
        .exclude(pk=academic_year.pk)
        .update(is_active=False)
    )

    academic_year.is_active = True
    academic_year.save(
        update_fields=[
            "is_active",
            "updated_at",
        ]
    )

    return academic_year


@transaction.atomic
def create_school_class(
*,
school,
validated_data: dict[str, Any],
) -> SchoolClass:
    """Create a class for a school."""

    school_class = SchoolClass(
        school=school,
        **validated_data,
    )

    school_class.full_clean()

    school_class.save()

    return school_class


@transaction.atomic
def update_school_class(
    *,
    school_class: SchoolClass,
    validated_data: dict[str, Any],
    school=None,
) -> SchoolClass:
    """
    Update a school class.

    If an authorized school is provided (School Admin),
    ensure the class belongs to that school.
    """

    if school is not None:
        validate_school_ownership(
            object_name="class",
            actual_school_id=school_class.school_id,
            expected_school_id=school.id,
            field_name="school",
        )

    for field, value in validated_data.items():
        setattr(school_class, field, value)

    school_class.full_clean()

    school_class.save(
        update_fields=[
            *validated_data.keys(),
            "updated_at",
        ],
    )

    return school_class


@transaction.atomic
def create_section(
*,
school,
validated_data: dict[str, Any],
) -> Section:
    """Create a section for a school."""

    section = Section(
        school=school,
        **validated_data,
    )

    section.full_clean()

    section.save()

    return section


@transaction.atomic
def update_section(
*,
section: Section,
validated_data: dict[str, Any],
) -> Section:
    """Update a section."""


    for field, value in validated_data.items():
        setattr(section, field, value)
        
    section.full_clean()

    section.save(
        update_fields=[
            *validated_data.keys(),
            "updated_at",
        ],
    )

    return section


@transaction.atomic
def create_class_section(
*,
school,
validated_data: dict[str, Any],
) -> ClassSection:
    """
    Create a class-section combination.

    The academic year, class, and section must all belong to the same
    school.
    """

    academic_year = validated_data["academic_year"]
    school_class = validated_data["school_class"]
    section = validated_data["section"]

    validate_school_ownership(
        object_name="academic year",
        actual_school_id=academic_year.school_id,
        expected_school_id=school.id,
        field_name="academic_year",
    )

    validate_school_ownership(
        object_name="class",
        actual_school_id=school_class.school_id,
        expected_school_id=school.id,
        field_name="school_class",
    )

    validate_school_ownership(
        object_name="section",
        actual_school_id=section.school_id,
        expected_school_id=school.id,
        field_name="section",
    )

    validate_same_school(
        academic_year=academic_year,
        school_class=school_class,
        section=section,
    )

    class_section = ClassSection(
        **validated_data,
    )

    class_section.full_clean()

    class_section.save()

    return class_section


@transaction.atomic
def update_class_section(
    *,
    class_section: ClassSection,
    validated_data: dict[str, Any],
    school,
) -> ClassSection:
    """
    Update a class-section combination.

    The academic year, class, and section must:
    1. Belong to the same school.
    2. Belong to the authorized school.
    """

    academic_year = validated_data.get(
        "academic_year",
        class_section.academic_year,
    )

    school_class = validated_data.get(
        "school_class",
        class_section.school_class,
    )

    section = validated_data.get(
        "section",
        class_section.section,
    )

    if school is not None:
        validate_authorized_school(
            authorized_school=school,
            academic_year=academic_year,
            school_class=school_class,
            section=section,
        )

    validate_same_school(
        academic_year=academic_year,
        school_class=school_class,
        section=section,
    )

    for field, value in validated_data.items():
        setattr(class_section, field, value)
        
    class_section.full_clean()

    class_section.save(
        update_fields=[
            *validated_data.keys(),
            "updated_at",
        ],
    )

    return class_section


DEFAULT_SYNCED_HOLIDAY_TITLE = "Holiday"


def sync_working_day_from_holiday(
    *,
    holiday: Holiday,
) -> WorkingDay:
    """
    Mark the holiday's date as a HOLIDAY working-day record.

    An existing record for that date is switched to HOLIDAY so the two
    tables cannot disagree.
    """

    working_day, _ = WorkingDay.objects.update_or_create(
        school_id=holiday.school_id,
        date=holiday.date,
        defaults={
            "academic_year_id": holiday.academic_year_id,
            "day_type": DayType.HOLIDAY,
            "remarks": holiday.title,
        },
    )

    return working_day


def sync_holiday_from_working_day(
    *,
    working_day: WorkingDay,
) -> Holiday:
    """
    Make sure a holiday exists for a date marked as HOLIDAY.

    An existing holiday keeps its own title unless the working-day
    record carries remarks to name it with.
    """

    remarks = (working_day.remarks or "").strip()

    holiday = Holiday.objects.filter(
        school_id=working_day.school_id,
        date=working_day.date,
    ).first()

    if holiday is None:
        return Holiday.objects.create(
            school_id=working_day.school_id,
            academic_year_id=working_day.academic_year_id,
            title=remarks or DEFAULT_SYNCED_HOLIDAY_TITLE,
            date=working_day.date,
        )

    update_fields = []

    if holiday.academic_year_id != working_day.academic_year_id:
        holiday.academic_year_id = working_day.academic_year_id
        update_fields.append("academic_year")

    if remarks and holiday.title != remarks:
        holiday.title = remarks
        update_fields.append("title")

    if update_fields:
        holiday.save(
            update_fields=[
                *update_fields,
                "updated_at",
            ],
        )

    return holiday


def remove_synced_working_day(
    *,
    school_id: int,
    target_date,
) -> None:
    """
    Drop the HOLIDAY working-day record for a date.

    Records of any other day type are left alone: they were not created
    by the holiday.
    """

    WorkingDay.objects.filter(
        school_id=school_id,
        date=target_date,
        day_type=DayType.HOLIDAY,
    ).delete()


def remove_synced_holiday(
    *,
    school_id: int,
    target_date,
) -> None:
    """Drop the holiday for a date that is no longer a holiday."""

    Holiday.objects.filter(
        school_id=school_id,
        date=target_date,
    ).delete()


@transaction.atomic
def create_holiday(
*,
school,
validated_data: dict[str, Any],
) -> Holiday:
    """Create a holiday for a school."""


    academic_year = validated_data["academic_year"]

    validate_academic_year_school(
        academic_year=academic_year,
        school_id=school.id,
    )

    validate_date_in_academic_year(
        academic_year=academic_year,
        target_date=validated_data["date"],
    )

    holiday = Holiday(
        school=school,
        **validated_data,
    )

    holiday.full_clean()

    holiday.save()

    sync_working_day_from_holiday(holiday=holiday)

    return holiday


@transaction.atomic
def update_holiday(
*,
holiday: Holiday,
validated_data: dict[str, Any],
) -> Holiday:
    """Update a holiday."""


    academic_year = validated_data.get(
        "academic_year",
        holiday.academic_year,
    )

    validate_academic_year_school(
        academic_year=academic_year,
        school_id=holiday.school_id,
    )

    validate_date_in_academic_year(
        academic_year=academic_year,
        target_date=validated_data.get(
            "date",
            holiday.date,
        ),
    )

    previous_date = holiday.date

    for field, value in validated_data.items():
        setattr(holiday, field, value)
        
    holiday.full_clean()

    holiday.save(
        update_fields=[
            *validated_data.keys(),
            "updated_at",
        ],
    )

    if holiday.date != previous_date:
        remove_synced_working_day(
            school_id=holiday.school_id,
            target_date=previous_date,
        )

    sync_working_day_from_holiday(holiday=holiday)

    return holiday


@transaction.atomic
def create_working_day(
*,
school,
validated_data: dict[str, Any],
) -> WorkingDay:
    """Create a working-day record for a school."""
    academic_year = validated_data["academic_year"]

    validate_academic_year_school(
        academic_year=academic_year,
        school_id=school.id,
    )

    validate_date_in_academic_year(
        academic_year=academic_year,
        target_date=validated_data["date"],
    )

    working_day = WorkingDay(
        school=school,
        **validated_data,
    )

    working_day.full_clean()

    working_day.save()

    if working_day.day_type == DayType.HOLIDAY:
        sync_holiday_from_working_day(working_day=working_day)

    return working_day


@transaction.atomic
def update_working_day(
*,
working_day: WorkingDay,
validated_data: dict[str, Any],
) -> WorkingDay:
    """
    Update a working-day record.

    When the date moves, or the day stops being a holiday, the holiday
    mirrored from the old state is removed.
    """


    academic_year = validated_data.get(
        "academic_year",
        working_day.academic_year,
    )

    validate_academic_year_school(
        academic_year=academic_year,
        school_id=working_day.school_id,
    )

    validate_date_in_academic_year(
        academic_year=academic_year,
        target_date=validated_data.get(
            "date",
            working_day.date,
        ),
    )

    previous_date = working_day.date
    was_holiday = working_day.day_type == DayType.HOLIDAY

    for field, value in validated_data.items():
        setattr(working_day, field, value)
        
    working_day.full_clean()

    working_day.save(
        update_fields=[
            *validated_data.keys(),
            "updated_at",
        ],
    )

    is_holiday = working_day.day_type == DayType.HOLIDAY

    if was_holiday and (
        not is_holiday
        or working_day.date != previous_date
    ):
        remove_synced_holiday(
            school_id=working_day.school_id,
            target_date=previous_date,
        )

    if is_holiday:
        sync_holiday_from_working_day(working_day=working_day)

    return working_day


@transaction.atomic
def delete_holiday(
    *,
    holiday: Holiday,
) -> None:
    """Delete a holiday and the working-day record mirroring it."""

    school_id = holiday.school_id
    holiday_date = holiday.date

    holiday.delete()

    remove_synced_working_day(
        school_id=school_id,
        target_date=holiday_date,
    )


@transaction.atomic
def delete_working_day(
    *,
    working_day: WorkingDay,
) -> None:
    """
    Delete a working-day record.

    If it marked the date as a holiday, the mirrored holiday goes with
    it.
    """

    school_id = working_day.school_id
    working_day_date = working_day.date
    was_holiday = working_day.day_type == DayType.HOLIDAY

    working_day.delete()

    if was_holiday:
        remove_synced_holiday(
            school_id=school_id,
            target_date=working_day_date,
        )


DEFAULT_WEEKEND_WEEKDAYS = (Weekday.SUNDAY,)


def iter_dates_matching_weekdays(
    *,
    start_date: date,
    end_date: date,
    weekdays,
):
    """
    Yield every date in the range falling on one of the weekdays.

    Weekdays are numbered the way ``date.weekday()`` numbers them
    (Monday is 0, Sunday is 6).
    """

    weekdays = {int(weekday) for weekday in weekdays}

    current = start_date

    while current <= end_date:
        if current.weekday() in weekdays:
            yield current

        current += timedelta(days=1)


@transaction.atomic
def mark_weekends(
    *,
    school,
    academic_year: AcademicYear,
    weekdays=DEFAULT_WEEKEND_WEEKDAYS,
    start_date: date | None = None,
    end_date: date | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Mark every matching weekday in a date range as a WEEKEND.

    Defaults to Sundays across the whole academic year.

    Dates that already carry a working-day record are left untouched
    unless ``overwrite`` is set, because an existing record is a
    deliberate choice by an administrator. When a holiday is overwritten,
    the holiday mirrored onto that date is removed as well so the two
    tables stay in sync. bulk_update() skips auto_now, so updated_at is
    stamped by hand.
    """

    validate_academic_year_school(
        academic_year=academic_year,
        school_id=school.id,
    )

    start_date = start_date or academic_year.start_date
    end_date = end_date or academic_year.end_date

    validate_date_in_academic_year(
        academic_year=academic_year,
        target_date=start_date,
        field_name="start_date",
    )

    validate_date_in_academic_year(
        academic_year=academic_year,
        target_date=end_date,
        field_name="end_date",
    )

    validate_academic_year_dates(
        start_date=start_date,
        end_date=end_date,
    )

    target_dates = list(
        iter_dates_matching_weekdays(
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays,
        )
    )

    if not target_dates:
        return {
            "matched": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
        }

    existing = {
        working_day.date: working_day
        for working_day in get_working_days_for_dates(
            school_id=school.id,
            dates=target_dates,
        )
    }

    to_create = []
    to_update = []
    holiday_dates_to_clear = []
    skipped = 0

    for target_date in target_dates:
        working_day = existing.get(target_date)

        if working_day is None:
            to_create.append(
                WorkingDay(
                    school=school,
                    academic_year=academic_year,
                    date=target_date,
                    day_type=DayType.WEEKEND,
                    remarks=Weekday(target_date.weekday()).label,
                )
            )
            continue

        if working_day.day_type == DayType.WEEKEND:
            skipped += 1
            continue

        if not overwrite:
            skipped += 1
            continue

        if working_day.day_type == DayType.HOLIDAY:
            holiday_dates_to_clear.append(target_date)

        working_day.academic_year = academic_year
        working_day.day_type = DayType.WEEKEND
        working_day.remarks = Weekday(target_date.weekday()).label
        working_day.updated_at = timezone.now()

        to_update.append(working_day)

    if to_create:
        WorkingDay.objects.bulk_create(to_create)

    if to_update:
        WorkingDay.objects.bulk_update(
            to_update,
            [
                "academic_year",
                "day_type",
                "remarks",
                "updated_at",
            ],
        )

    for holiday_date in holiday_dates_to_clear:
        remove_synced_holiday(
            school_id=school.id,
            target_date=holiday_date,
        )

    return {
        "matched": len(target_dates),
        "created": len(to_create),
        "updated": len(to_update),
        "skipped": skipped,
    }
