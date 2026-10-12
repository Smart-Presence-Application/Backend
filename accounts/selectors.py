from django.db.models import Q

from accounts.models import User
from common.choices import UserRole


def is_global_user_admin(actor) -> bool:
    """Super admins may act on every user; school admins may not."""
    return bool(actor and (actor.is_superuser or actor.role == UserRole.SUPER_ADMIN))


def get_users_visible_to(actor):
    """Users `actor` is allowed to read and manage.

    Super admins get every user. A school admin gets the staff of the school
    they manage, plus their own record. Anyone else gets nothing.
    """
    if is_global_user_admin(actor):
        return User.objects.all()

    school = getattr(actor, "managed_school", None)

    if school is None:
        return User.objects.none()

    return User.objects.filter(
        Q(pk=actor.pk) | Q(teacher_profile__school=school)
    ).distinct()


def get_user_by_id(user_id, *, actor=None):
    queryset = User.objects.all() if actor is None else get_users_visible_to(actor)
    return queryset.filter(pk=user_id).first()


def get_users(*, actor=None):
    return User.objects.all() if actor is None else get_users_visible_to(actor)


def get_users_by_ids(user_ids, *, actor=None):
    queryset = User.objects.all() if actor is None else get_users_visible_to(actor)
    return queryset.filter(id__in=user_ids)
