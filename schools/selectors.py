from django.db.models import QuerySet

from .models import School


def school_queryset() -> QuerySet[School]:
    """Base queryset for schools, with their admin loaded."""
    return (
        School.objects.select_related("admin").all()
    )


def get_school(school_id: int) -> School | None:
    """Return a school by its ID."""
    return school_queryset().filter(id=school_id).first()


def get_school_by_admin(admin_id: int) -> School | None:
    """Return the school managed by the given admin."""
    return school_queryset().filter(admin_id=admin_id).first()


def list_schools() -> QuerySet[School]:
    """Return all schools, newest first."""
    return school_queryset().order_by("-created_at")