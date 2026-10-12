from django.db import transaction

from accounts.models import User
from common.choices import Status, UserRole
from common.utils import generate_random_password
from .signals import (
    school_activated,
    school_deactivated,
)

from .models import School


@transaction.atomic
def create_school(*, validated_data: dict) -> School:
    """Create a school and its admin user."""
    school_data = validated_data["school"]
    admin_data = validated_data["admin"]

    password = generate_random_password()

    admin = User.objects.create_user(
        email=admin_data["email"],
        name=admin_data["name"],
        phone_number=admin_data["phone_number"],
        password=password,
        role=UserRole.SCHOOL_ADMIN,
        is_active=False,
    )

    school = School.objects.create(
        **school_data,
        admin=admin,
        status=Status.INACTIVE,
    )

    return school


@transaction.atomic
def update_school(*, school: School, validated_data: dict) -> School:
    """Update school details."""
    for field, value in validated_data.items():
        setattr(school, field, value)

    school.save()

    return school


@transaction.atomic
def delete_school(*, school: School) -> None:
    admin = school.admin

    school.delete()
    admin.delete()


@transaction.atomic
def change_school_status(
    *,
    school: School,
    status: str,
) -> School:
    """Activate or deactivate a school and its admin."""
    if school.status == status:
        return school

    school.status = status
    school.save(update_fields=["status"])

    if status == Status.ACTIVE:
        password = generate_random_password()

        school.admin.set_password(password)
        school.admin.is_active = True
        school.admin.save(
            update_fields=[
                "password",
                "is_active",
            ]
        )

        transaction.on_commit(
            lambda: school_activated.send(
                sender=School,
                school=school,
                password=password,
            )
        )

    else:
        school.admin.is_active = False
        school.admin.save(update_fields=["is_active"])

        transaction.on_commit(
            lambda: school_deactivated.send(
                sender=School,
                school=school,
            )
        )

    return school

