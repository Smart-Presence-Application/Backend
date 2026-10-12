from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.choices import DayType
from schools.models import School


class AcademicYear(models.Model):
    """
    Represents an academic year belonging to a school.

    A school can have multiple academic years, but only one academic
    year can be active at a time.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="academic_years",
    )
    name = models.CharField(
        max_length=20,
        help_text="Example: 2026-27",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "academic_years"
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_academic_year_name_per_school",
            ),
            models.UniqueConstraint(
                fields=["school"],
                condition=Q(
                    is_active=True,
                ),
                name="only_one_active_academic_year_per_school",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "start_date", "end_date"],
                name="academic_year_school_dates_idx",
            ),
            models.Index(
                fields=["school", "is_active"],
                name="academic_year_schl_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school.name} - {self.name}"
    
    
class SchoolClass(models.Model):
    """
    Represents a class structure defined by a school.

    Examples:

    - Play Group
    - Nursery
    - LKG
    - UKG
    - Class 1
    - Class 12
    """

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="classes",
    )
    name = models.CharField(max_length=100)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "school_classes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_class_name_per_school",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school.name} - {self.name}"
    
    
class Section(models.Model):
    """
    Represents a section defined by a school.

    Examples:

    - A
    - B
    - C
    - D
    """

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="sections",
    )
    name = models.CharField(max_length=50)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "sections"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="unique_section_name_per_school",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school.name} - {self.name}"
    

class ClassSection(models.Model):
    """
    Represents a class-section combination for an academic year.

    Example:

        Academic Year: 2026-27
        Class: Class 5
        Section: A

    The class, section, and academic year must all belong to
    the same school.
    """

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="class_sections",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="class_sections",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="class_sections",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "class_sections"
        ordering = [
            "academic_year__start_date",
            "school_class__name",
            "section__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "academic_year",
                    "school_class",
                    "section",
                ],
                name="unique_class_section_per_academic_year",
            ),
        ]
        indexes = [
            models.Index(
                fields=["academic_year"],
                name="class_section_year_idx",
            ),
            models.Index(
                fields=["school_class", "section"],
                name="school_class_section_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.academic_year.name} - "
            f"{self.school_class.name} - "
            f"{self.section.name}"
        )

    def clean(self) -> None:
        """Ensure all related entities belong to the same school."""

        if (
            self.academic_year_id
            and self.school_class_id
            and self.academic_year.school_id
            != self.school_class.school_id
        ):
            raise ValidationError(
                {
                    "school_class": (
                        "The class must belong to the same school "
                        "as the academic year."
                    )
                }
            )

        if (
            self.academic_year_id
            and self.section_id
            and self.academic_year.school_id
            != self.section.school_id
        ):
            raise ValidationError(
                {
                    "section": (
                        "The section must belong to the same school "
                        "as the academic year."
                    )
                }
            )

        if (
            self.school_class_id
            and self.section_id
            and self.school_class.school_id
            != self.section.school_id
        ):
            raise ValidationError(
                {
                    "section": (
                        "The section must belong to the same school "
                        "as the class."
                    )
                }
            )
    
    
class Holiday(models.Model):
    """
    Represents a holiday for a school.

    A school can have only one holiday record for a particular date.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="holidays",
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="holidays",
    )
    title = models.CharField(max_length=255)
    date = models.DateField()
    description = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "holidays"
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "date"],
                name="unique_holiday_per_school_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "date"],
                name="holiday_school_date_idx",
            ),
            models.Index(
                fields=["academic_year", "date"],
                name="holiday_year_date_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school.name} - {self.title} - {self.date}"

    def clean(self) -> None:
        """Ensure the academic year belongs to the same school."""

        if (
            self.school_id
            and self.academic_year_id
            and self.school_id != self.academic_year.school_id
        ):
            raise ValidationError(
                {
                    "academic_year": (
                        "The academic year must belong to the same school."
                    )
                }
            )

        if (
            self.academic_year_id
            and self.date
            and not (
                self.academic_year.start_date
                <= self.date
                <= self.academic_year.end_date
            )
        ):
            raise ValidationError(
                {
                    "date": (
                        "Holiday date must fall within the academic "
                        "year dates."
                    )
                }
            )
    
    
class WorkingDay(models.Model):
    """
    Represents the working-day status of a particular date.

    If no record exists for a date, the system can determine the
    default status based on the school's configured weekly off days.

    Explicit records override the default calendar behavior.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="working_days",
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="working_days",
    )
    date = models.DateField()
    day_type = models.CharField(
        max_length=20,
        choices=DayType.choices,
    )
    remarks = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "working_days"
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "date"],
                name="unique_working_day_per_school_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "date"],
                name="working_day_school_date_idx",
            ),
            models.Index(
                fields=["academic_year", "date"],
                name="working_day_year_date_idx",
            ),
            models.Index(
                fields=["school", "day_type"],
                name="working_day_school_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.school.name} - "
            f"{self.date} - "
            f"{self.get_day_type_display()}"
        )

    @property
    def is_working_day(self) -> bool:
        """Whether the day counts as a working day; EVENT days deliberately do."""

        return self.day_type in {
            DayType.WORKING,
            DayType.EVENT,
        }

    def clean(self) -> None:
        """
        Ensure the academic year belongs to the same school and the
        date falls within the academic year.
        """

        if (
            self.school_id
            and self.academic_year_id
            and self.school_id != self.academic_year.school_id
        ):
            raise ValidationError(
                {
                    "academic_year": (
                        "The academic year must belong to the same school."
                    )
                }
            )

        if (
            self.academic_year_id
            and self.date
            and not (
                self.academic_year.start_date
                <= self.date
                <= self.academic_year.end_date
            )
        ):
            raise ValidationError(
                {
                    "date": (
                        "Working day date must fall within the academic "
                        "year dates."
                    )
                }
            )
