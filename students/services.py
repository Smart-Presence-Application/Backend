"""Business logic for student management."""

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Student
from .validators import (
    validate_class_section_school,
    validate_roll_number_available,
    validate_student_id_available,
)

logger = logging.getLogger(__name__)


@transaction.atomic
def create_student(
    *,
    class_section,
    validated_data: dict[str, Any],
) -> Student:
    """
    Enrol a student in a class-section.

    The school is taken from the class-section rather than the caller,
    so the two can never disagree.

    A profile image is attached in a second save: the upload path is
    built from the student's primary key, which does not exist until
    the row has been written once.
    """

    school = class_section.academic_year.school

    profile_image = validated_data.pop("profile_image", None)

    validate_student_id_available(
        school_id=school.id,
        student_id=validated_data["student_id"].strip().upper(),
    )

    validate_roll_number_available(
        class_section_id=class_section.id,
        roll_number=validated_data["roll_number"].strip(),
    )

    student = Student(
        school=school,
        class_section=class_section,
        **validated_data,
    )

    student.full_clean()

    student.save()

    if profile_image is not None:
        student.profile_image = profile_image
        student.save(
            update_fields=[
                "profile_image",
                "updated_at",
            ],
        )

    logger.info(
        "Student %s enrolled in class section %s",
        student.student_id,
        class_section.id,
    )

    return student


@transaction.atomic
def update_student(
    *,
    student: Student,
    validated_data: dict[str, Any],
    class_section=None,
) -> Student:
    """
    Update a student, optionally moving them to another class-section.

    The caller is responsible for checking that ``class_section`` is
    one they are allowed to use; the school is re-derived from it here.
    A move can collide with a roll number already used in the destination,
    so the roll number is re-checked whenever either half of the pair
    changes.
    """

    if class_section is not None:
        validate_class_section_school(
            class_section=class_section,
            school=class_section.academic_year.school,
        )

        student.class_section = class_section
        student.school = class_section.academic_year.school

    for field, value in validated_data.items():
        setattr(student, field, value)

    if "student_id" in validated_data:
        validate_student_id_available(
            school_id=student.school_id,
            student_id=student.student_id.strip().upper(),
            instance=student,
        )

    if "roll_number" in validated_data or class_section is not None:
        validate_roll_number_available(
            class_section_id=student.class_section_id,
            roll_number=student.roll_number.strip(),
            instance=student,
        )

    student.full_clean()

    student.save()

    return student


@transaction.atomic
def update_student_profile_image(
    *,
    student: Student,
    image,
) -> Student:
    """
    Replace a student's profile image.

    The old file is removed so stale images do not accumulate in
    storage once the embedding has been rebuilt from the new one.
    """

    old_image = student.profile_image

    if old_image and old_image != image:
        old_image.delete(save=False)

    student.profile_image = image
    student.save(
        update_fields=[
            "profile_image",
            "updated_at",
        ],
    )

    logger.info(
        "Profile image updated for student %s",
        student.student_id,
    )

    return student


@transaction.atomic
def delete_student(
    *,
    student: Student,
) -> None:
    """Delete a student and their stored profile image."""

    student_id = student.student_id
    image = student.profile_image

    student.delete()

    if image:
        image.delete(save=False)

    logger.info("Student %s deleted", student_id)


ROLL_KEEP = "keep"
ROLL_RENUMBER = "renumber"
ROLL_ALPHABETICAL = "alphabetical"
ROLL_CHOICES = (
    (ROLL_KEEP, "Keep current roll numbers"),
    (ROLL_RENUMBER, "Renumber 1, 2, 3... in current roll order"),
    (ROLL_ALPHABETICAL, "Renumber 1, 2, 3... in name order"),
)


def _natural_roll(roll: str) -> str:
    return roll.zfill(20)


@transaction.atomic
def promote_students(*, students, to_class_section, roll_numbers: str = ROLL_KEEP) -> list[Student]:
    """
    Move students into another class-section, typically the next class
    in the next academic year.

    Each student keeps their record, photo and face registration; past
    attendance stays with the class-section it was taken in. Roll numbers
    are kept, or reassigned 1, 2, 3... (skipping numbers already used in
    the destination) in current roll order or by name.

    All or nothing: any problem raises ValidationError and nobody moves.
    Only the student rows are locked, since the scoped queryset also joins
    optional relations. Rolls are written in two passes so students
    swapping roll numbers never trip the one-roll-per-section constraint
    halfway through.
    """

    students = list(students.select_for_update(of=("self",)))
    school = to_class_section.academic_year.school

    errors = []

    if not students:
        errors.append("Choose at least one student.")

    other_school = [s.student_id for s in students if s.school_id != school.id]
    if other_school:
        errors.append(f"These students are in another school: {', '.join(other_school)}.")

    already_there = [s.student_id for s in students if s.class_section_id == to_class_section.id]
    if already_there:
        errors.append(f"Already in this class section: {', '.join(already_there)}.")

    if errors:
        raise ValidationError({"student_ids": errors})

    moving = {s.pk for s in students}
    taken = set(
        Student.objects.filter(class_section=to_class_section)
        .exclude(pk__in=moving)
        .values_list("roll_number", flat=True)
    )

    if roll_numbers == ROLL_KEEP:
        seen: dict[str, str] = {}
        clashes = []

        for s in students:
            roll = s.roll_number.strip()
            if roll in taken:
                clashes.append(f"roll {roll} ({s.student_id}) is already used in the destination")
            elif roll in seen:
                clashes.append(f"roll {roll} is shared by {seen[roll]} and {s.student_id}")
            seen.setdefault(roll, s.student_id)

        if clashes:
            raise ValidationError(
                {"roll_numbers": [f"Cannot keep roll numbers: {'; '.join(clashes)}. Choose to renumber instead."]}
            )

        new_rolls = {s.pk: s.roll_number.strip() for s in students}
    else:
        if roll_numbers == ROLL_ALPHABETICAL:
            ordered = sorted(students, key=lambda s: (s.name.lower(), s.student_id))
        else:
            ordered = sorted(
                students,
                key=lambda s: (s.class_section_id, _natural_roll(s.roll_number.strip()), s.student_id),
            )

        new_rolls = {}
        number = 0

        for s in ordered:
            number += 1
            while str(number) in taken:
                number += 1
            new_rolls[s.pk] = str(number)

    now = timezone.now()

    for s in students:
        s.roll_number = f"~{s.pk}"
    Student.objects.bulk_update(students, ["roll_number"])

    for s in students:
        s.class_section = to_class_section
        s.school = school
        s.roll_number = new_rolls[s.pk]
        s.updated_at = now
    Student.objects.bulk_update(students, ["class_section", "school", "roll_number", "updated_at"])

    logger.info(
        "Promoted %s student(s) to class section %s (roll numbers: %s)",
        len(students),
        to_class_section.pk,
        roll_numbers,
    )

    return students
