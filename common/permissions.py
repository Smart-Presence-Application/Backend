"""Shared permission helpers."""
from rest_framework.permissions import BasePermission
from accounts.models import UserRole

class HasRolePermission(BasePermission):
    roles: tuple[str, ...] = ()

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.role in self.roles)


class IsSuperAdmin(HasRolePermission):
    roles = (UserRole.SUPER_ADMIN,)


class IsSchoolAdmin(HasRolePermission):
    roles = (UserRole.SCHOOL_ADMIN,)


class IsTeacher(HasRolePermission):
    roles = (UserRole.TEACHER,)


class IsSuperOrSchoolAdmin(HasRolePermission):
    roles = (UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN)


class IsStudentManager(HasRolePermission):
    """Gate for student routes.

    All three roles may reach these routes; the queryset scoping in
    students.selectors decides which students each one actually sees.
    """

    roles = (UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER)


class IsAttendanceManager(IsStudentManager):
    """Gate for attendance and face-registration routes.

    Scoping in attendance_student.selectors decides what each role sees;
    whether a locked attendance may still be edited is decided in
    attendance_student.services.
    """


class IsParent(HasRolePermission):
    roles = (UserRole.PARENT,)


class IsParentManager(IsStudentManager):
    """Gate for creating and managing parents.

    Teachers manage the parents of their own class-section's students;
    scoping lives in parents.selectors.
    """


class IsNotificationSender(IsStudentManager):
    """Gate for sending notifications.

    Super Admins, School Admins and teachers may send; who each may
    reach is decided in notifications.selectors.
    """


class IsAcademicAdmin(IsSuperOrSchoolAdmin):
    pass


class IsUserAdmin(BasePermission):
    """Gate for user-administration routes.

    Super admins are allowed globally; school admins are allowed here but are
    restricted to their own school by the queryset scoping in accounts.selectors.
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and (
                user.is_superuser
                or user.role in (UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN)
            )
        )
