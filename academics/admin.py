from django.contrib import admin

from common.choices import DayType

from .models import (
    AcademicYear,
    SchoolClass,
    Section,
    ClassSection,
    Holiday,
    WorkingDay,
)
from .services import (
    remove_synced_holiday,
    remove_synced_working_day,
    sync_holiday_from_working_day,
    sync_working_day_from_holiday,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "school",
        "start_date",
        "end_date",
        "is_active",
        "created_at",
    )
    list_filter = (
        "is_active",
        "school",
        "start_date",
    )
    search_fields = (
        "name",
        "school__name",
        "school__code",
    )
    ordering = (
        "school__name",
        "-start_date",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "school",
    )


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "school",
        "created_at",
    )
    list_filter = (
        "school",
    )
    search_fields = (
        "name",
        "school__name",
        "school__code",
    )
    ordering = (
        "school__name",
        "name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "school",
    )


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "school",
        "created_at",
    )
    list_filter = (
        "school",
    )
    search_fields = (
        "name",
        "school__name",
        "school__code",
    )
    ordering = (
        "school__name",
        "name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "school",
    )


@admin.register(ClassSection)
class ClassSectionAdmin(admin.ModelAdmin):
    list_display = (
        "academic_year",
        "school_class",
        "section",
        "created_at",
    )
    list_filter = (
        "academic_year__school",
        "academic_year",
    )
    search_fields = (
        "academic_year__name",
        "school_class__name",
        "section__name",
        "academic_year__school__name",
    )
    ordering = (
        "academic_year__school__name",
        "academic_year__name",
        "school_class__name",
        "section__name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "academic_year",
        "school_class",
        "section",
    )


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    """Saves and deletes here keep the mirrored working-day records in sync, as the services do."""

    list_display = (
        "title",
        "school",
        "academic_year",
        "date",
        "created_at",
    )
    list_filter = (
        "school",
        "academic_year",
        "date",
    )
    search_fields = (
        "title",
        "school__name",
        "academic_year__name",
    )
    ordering = (
        "school__name",
        "date",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "school",
        "academic_year",
    )

    def save_model(self, request, obj, form, change):
        previous_date = None

        if change and "date" in form.changed_data:
            previous_date = form.initial.get("date")

        super().save_model(request, obj, form, change)

        if previous_date and previous_date != obj.date:
            remove_synced_working_day(
                school_id=obj.school_id,
                target_date=previous_date,
            )

        sync_working_day_from_holiday(holiday=obj)

    def delete_model(self, request, obj):
        school_id = obj.school_id
        holiday_date = obj.date

        super().delete_model(request, obj)

        remove_synced_working_day(
            school_id=school_id,
            target_date=holiday_date,
        )

    def delete_queryset(self, request, queryset):
        deleted = list(
            queryset.values_list("school_id", "date")
        )

        super().delete_queryset(request, queryset)

        for school_id, holiday_date in deleted:
            remove_synced_working_day(
                school_id=school_id,
                target_date=holiday_date,
            )


@admin.register(WorkingDay)
class WorkingDayAdmin(admin.ModelAdmin):
    """Saves and deletes here keep the mirrored holidays in sync, as the services do."""

    list_display = (
        "school",
        "academic_year",
        "date",
        "day_type",
        "is_working_day",
        "created_at",
    )
    list_filter = (
        "school",
        "academic_year",
        "day_type",
        "date",
    )
    search_fields = (
        "school__name",
        "academic_year__name",
        "remarks",
    )
    ordering = (
        "school__name",
        "date",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "is_working_day",
    )
    autocomplete_fields = (
        "school",
        "academic_year",
    )

    def save_model(self, request, obj, form, change):
        previous_date = None
        was_holiday = False

        if change:
            previous_date = form.initial.get("date")
            was_holiday = (
                form.initial.get("day_type") == DayType.HOLIDAY
            )

        super().save_model(request, obj, form, change)

        is_holiday = obj.day_type == DayType.HOLIDAY

        if was_holiday and previous_date and (
            not is_holiday
            or obj.date != previous_date
        ):
            remove_synced_holiday(
                school_id=obj.school_id,
                target_date=previous_date,
            )

        if is_holiday:
            sync_holiday_from_working_day(working_day=obj)

    def delete_model(self, request, obj):
        school_id = obj.school_id
        working_day_date = obj.date
        was_holiday = obj.day_type == DayType.HOLIDAY

        super().delete_model(request, obj)

        if was_holiday:
            remove_synced_holiday(
                school_id=school_id,
                target_date=working_day_date,
            )

    def delete_queryset(self, request, queryset):
        deleted = list(
            queryset.filter(
                day_type=DayType.HOLIDAY,
            ).values_list("school_id", "date")
        )

        super().delete_queryset(request, queryset)

        for school_id, working_day_date in deleted:
            remove_synced_holiday(
                school_id=school_id,
                target_date=working_day_date,
            )
