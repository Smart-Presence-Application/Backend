"""
Business logic for teacher management.

USER_FIELDS lists the fields that live on the user record rather than the
teacher profile.
"""

import logging
from typing import Any

from django.db import transaction

from accounts.models import User
from accounts.services import set_user_status
from accounts.signals import user_created
from common.choices import UserRole
from common.utils import generate_random_password

from .models import Teacher
from .validators import (
    validate_class_section_school,
    validate_email_available,
    validate_employee_id_available,
)

logger = logging.getLogger(__name__)

USER_FIELDS = (
    "name",
    "email",
    "phone_number",
    "gender",
)


def split_teacher_payload(
    validated_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a flat payload into user fields and teacher-profile fields."""

    user_data = {
        field: validated_data[field]
        for field in USER_FIELDS
        if field in validated_data
    }

    profile_data = {
        field: value
        for field, value in validated_data.items()
        if field not in USER_FIELDS
    }

    return user_data, profile_data


@transaction.atomic
def create_teacher(
    *,
    school,
    validated_data: dict[str, Any],
) -> Teacher:
    """
    Create a teacher and the inactive login that goes with it.

    The account starts inactive and without a usable password. The
    password is generated and emailed when an administrator activates
    the teacher, so no credential is ever stored in the clear or sent
    before the account can be used.
    """

    user_data, profile_data = split_teacher_payload(validated_data)

    validate_email_available(email=user_data["email"])

    validate_employee_id_available(
        school_id=school.id,
        employee_id=profile_data["employee_id"],
    )

    class_section = profile_data.get("class_section")

    if class_section is not None:
        validate_class_section_school(
            class_section=class_section,
            school_id=school.id,
        )

    user = User.objects.create_user(
        password=None,
        role=UserRole.TEACHER,
        is_active=False,
        **user_data,
    )

    teacher = Teacher(
        user=user,
        school=school,
        **profile_data,
    )

    teacher.full_clean(exclude=["user"])

    teacher.save()

    logger.info(
        "Teacher %s created for school %s",
        teacher.employee_id,
        school.id,
    )

    return teacher


@transaction.atomic
def update_teacher(
    *,
    teacher: Teacher,
    validated_data: dict[str, Any],
) -> Teacher:
    """Update a teacher profile and the user fields that travel with it."""

    user_data, profile_data = split_teacher_payload(validated_data)

    if "email" in user_data:
        validate_email_available(
            email=user_data["email"],
            instance=teacher,
        )

    if "employee_id" in profile_data:
        validate_employee_id_available(
            school_id=teacher.school_id,
            employee_id=profile_data["employee_id"],
            instance=teacher,
        )

    if profile_data.get("class_section") is not None:
        validate_class_section_school(
            class_section=profile_data["class_section"],
            school_id=teacher.school_id,
        )

    if user_data:
        for field, value in user_data.items():
            setattr(teacher.user, field, value)

        teacher.user.save(
            update_fields=[
                *user_data.keys(),
                "updated_at",
            ],
        )

    if profile_data:
        for field, value in profile_data.items():
            setattr(teacher, field, value)

        teacher.full_clean(exclude=["user"])

        teacher.save(
            update_fields=[
                *profile_data.keys(),
                "updated_at",
            ],
        )

    return teacher


@transaction.atomic
def delete_teacher(
    *,
    teacher: Teacher,
) -> None:
    """
    Delete a teacher along with the login it owns.

    Deleting the user cascades to the profile, so the two can never be
    left half-removed.
    """

    employee_id = teacher.employee_id
    user = teacher.user

    user.delete()

    logger.info("Teacher %s deleted", employee_id)


@transaction.atomic
def set_teacher_status(
    *,
    teacher: Teacher,
    is_active: bool,
    changed_by=None,
) -> bool:
    """
    Activate or deactivate a teacher's login.

    Activating issues a fresh password and emails it to the teacher
    through the account-created signal. Raw passwords are never stored,
    so a new one has to be generated at the moment of activation rather
    than reused from account creation. The email is sent only after commit,
    so a rolled-back activation cannot leak a password for an account that
    does not exist.

    Returns True when the status actually changed.
    """

    user = teacher.user

    if user.is_active == is_active:
        return False

    if not is_active:
        return set_user_status(
            user,
            False,
            changed_by=changed_by,
        )

    raw_password = generate_random_password()

    user.set_password(raw_password)
    user.is_active = True
    user.save(
        update_fields=[
            "password",
            "is_active",
            "updated_at",
        ],
    )

    logger.info(
        "Teacher %s activated by %s",
        teacher.employee_id,
        getattr(changed_by, "email", changed_by),
    )

    transaction.on_commit(
        lambda: user_created.send(
            sender=user.__class__,
            user=user,
            raw_password=raw_password,
        )
    )

    return True


@transaction.atomic
def assign_class_section(
    *,
    teacher: Teacher,
    class_section,
) -> Teacher:
    """
    Assign a class-section to a teacher.

    A teacher holds one class-section at a time, so assigning replaces
    whatever they held before.
    """

    validate_class_section_school(
        class_section=class_section,
        school_id=teacher.school_id,
    )

    teacher.class_section = class_section
    teacher.save(
        update_fields=[
            "class_section",
            "updated_at",
        ],
    )

    logger.info(
        "Teacher %s assigned to class section %s",
        teacher.employee_id,
        class_section.id,
    )

    return teacher


@transaction.atomic
def revoke_class_section(
    *,
    teacher: Teacher,
) -> bool:
    """
    Clear a teacher's class-section assignment.

    Returns True when there was an assignment to clear.
    """

    if teacher.class_section_id is None:
        return False

    previous_id = teacher.class_section_id

    teacher.class_section = None
    teacher.save(
        update_fields=[
            "class_section",
            "updated_at",
        ],
    )

    logger.info(
        "Teacher %s revoked from class section %s",
        teacher.employee_id,
        previous_id,
    )

    return True


@transaction.atomic
def transfer_class_section(
    *,
    teacher: Teacher,
    class_section,
):
    """
    Move a teacher from their current class-section to another one.

    Returns the teacher and the class-section they came from.
    """

    previous = teacher.class_section

    validate_class_section_school(
        class_section=class_section,
        school_id=teacher.school_id,
    )

    teacher.class_section = class_section
    teacher.save(
        update_fields=[
            "class_section",
            "updated_at",
        ],
    )

    logger.info(
        "Teacher %s transferred from %s to %s",
        teacher.employee_id,
        getattr(previous, "id", None),
        class_section.id,
    )

    return teacher, previous
