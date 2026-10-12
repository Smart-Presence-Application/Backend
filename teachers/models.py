from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from academics.models import ClassSection
from schools.models import School


class Teacher(models.Model):
    """
    A teacher's school-side profile.

    Login credentials live on the linked user; everything specific to
    the teacher's employment lives here.

    A teacher holds at most one class-section at a time. The assignment
    is stored on this row rather than in a join table because the
    relationship is one-to-one from the teacher's side.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="teacher_profile",
    )
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="teachers",
    )
    employee_id = models.CharField(max_length=50)

    class_section = models.ForeignKey(
        ClassSection,
        on_delete=models.PROTECT,
        related_name="teachers",
        null=True,
        blank=True,
    )

    address = models.TextField(
        blank=True,
        default="",
    )
    city = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    state = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    country = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    pincode = models.CharField(
        max_length=20,
        blank=True,
        default="",
    )
    joining_date = models.DateField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teachers"
        ordering = ["employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "employee_id"],
                name="unique_employee_id_per_school",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "employee_id"],
                name="teacher_school_employee_idx",
            ),
            models.Index(
                fields=["school", "class_section"],
                name="teacher_school_section_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} - {self.user.name}"

    def clean(self) -> None:
        """Keep the employee id tidy and the class-section in-school."""

        if self.employee_id:
            self.employee_id = self.employee_id.strip().upper()

        if (
            self.school_id
            and self.class_section_id
            and self.class_section.academic_year.school_id != self.school_id
        ):
            raise ValidationError(
                {
                    "class_section": (
                        "The class section must belong to the same "
                        "school as the teacher."
                    )
                }
            )
