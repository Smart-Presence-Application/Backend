from django.core.exceptions import ValidationError
from django.db import models

from academics.models import ClassSection
from common.ordering import roll_order
from common.storage import std_profile_image_upload_path
from common.validators import validate_image_file
from schools.models import School


class Student(models.Model):
    """
    A student enrolled in a class-section.

    Students are records, not logins: they never sign in, so there is
    no user attached.

    ``school`` duplicates what ``class_section`` already implies. It is
    stored so the database itself can enforce one student ID per
    school, and it is derived from the class-section on every write
    rather than accepted from the caller.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="students",
    )
    class_section = models.ForeignKey(
        ClassSection,
        on_delete=models.PROTECT,
        related_name="students",
    )

    name = models.CharField(max_length=255)
    student_id = models.CharField(max_length=50)
    roll_number = models.CharField(max_length=20)

    profile_image = models.ImageField(
        upload_to=std_profile_image_upload_path,
        blank=True,
        null=True,
        validators=[validate_image_file],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "students"
        ordering = ["class_section", roll_order()]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "student_id"],
                name="unique_student_id_per_school",
            ),
            models.UniqueConstraint(
                fields=["class_section", "roll_number"],
                name="unique_roll_number_per_class_section",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "student_id"],
                name="student_school_id_idx",
            ),
            models.Index(
                fields=["class_section", "roll_number"],
                name="student_section_roll_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student_id} - {self.name}"

    @property
    def has_profile_image(self) -> bool:
        """Whether a face embedding can be built for this student."""

        return bool(self.profile_image)

    def clean(self) -> None:
        """Normalise the identifiers and keep school and section agreeing."""

        if self.student_id:
            self.student_id = self.student_id.strip().upper()

        if self.roll_number:
            self.roll_number = self.roll_number.strip()

        if self.name:
            self.name = self.name.strip()

        if (
            self.school_id
            and self.class_section_id
            and self.class_section.academic_year.school_id != self.school_id
        ):
            raise ValidationError(
                {
                    "class_section": (
                        "The class section must belong to the same "
                        "school as the student."
                    )
                }
            )
