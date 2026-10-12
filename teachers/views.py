"""Teacher API views."""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from common.pagination import StandardResultsPagination
from common.permissions import IsSuperAdmin, IsSuperOrSchoolAdmin, IsTeacher
from common.responses import (
    created_response,
    deleted_response,
    error_response,
    not_found_response,
    success_response,
    updated_response,
)

from .csv_import import CSVImportError, import_teachers_from_csv
from .teacher_filters import TeacherFilter
from .selectors import (
    get_teacher,
    get_teacher_profile,
    get_teachers_visible_to,
)
from .serializers import (
    ClassSectionAssignmentSerializer,
    TeacherBulkUploadSerializer,
    TeacherCreateSerializer,
    TeacherCSVRowSerializer,
    TeacherDetailSerializer,
    TeacherListSerializer,
    TeacherProfileSerializer,
    TeacherStatusSerializer,
    TeacherUpdateSerializer,
)
from .services import (
    assign_class_section,
    create_teacher,
    delete_teacher,
    revoke_class_section,
    set_teacher_status,
    transfer_class_section,
    update_teacher,
)

logger = logging.getLogger(__name__)


class TeacherBaseMixin:
    """Shared helpers for school-scoped teacher views."""

    def is_super_admin(self) -> bool:
        return IsSuperAdmin().has_permission(
            self.request,
            self,
        )

    def get_user_school(self):
        """Return the school managed by the authenticated School Admin."""

        school = getattr(
            self.request.user,
            "managed_school",
            None,
        )

        if school is None:
            raise ValidationError(
                {
                    "detail": (
                        "The authenticated user is not assigned "
                        "as an administrator of any school."
                    )
                }
            )

        return school

    def resolve_school(self, validated_data):
        """
        Pick the school to act on.

        Super Admins name it in the payload; School Admins always get
        their own, whatever the payload says.
        """

        if self.is_super_admin():
            return validated_data["school"]

        return self.get_user_school()

    def get_teacher_or_404(self, pk):
        """
        Fetch a teacher the actor is allowed to see.

        A teacher outside the actor's school is reported as missing
        rather than forbidden, so an administrator cannot probe for
        teachers in other schools.

        A database error is reported as missing too, so a broken lookup
        never reaches the caller as a 500. The exception is logged at
        error level first, because the usual cause is an unapplied
        migration and that has to stay visible to whoever runs the
        server.
        """

        try:
            teacher = get_teacher(pk, actor=self.request.user)
        except DatabaseError:
            logger.exception(
                "Teacher lookup failed for pk=%s. The teachers schema "
                "is probably out of date - check for unapplied "
                "migrations.",
                pk,
            )
            raise NotFound("Teacher not found.")

        if teacher is None:
            raise NotFound("Teacher not found.")

        return teacher


class TeacherListCreateAPIView(
    TeacherBaseMixin,
    generics.ListCreateAPIView,
):
    """
    List teachers and create new ones.

    Teachers are created inactive and without a usable password. They
    receive their credentials by email when an administrator activates
    them.
    """

    permission_classes = [
        IsAuthenticated,
        IsSuperOrSchoolAdmin,
    ]
    pagination_class = StandardResultsPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = TeacherFilter
    search_fields = [
        "employee_id",
        "user__name",
        "user__email",
        "user__phone_number",
    ]
    ordering_fields = [
        "employee_id",
        "user__name",
        "joining_date",
        "created_at",
    ]
    ordering = ["employee_id"]

    def get_queryset(self):
        return get_teachers_visible_to(self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TeacherCreateSerializer

        return TeacherListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        return success_response(
            "Teachers fetched successfully.",
            serializer.data,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = dict(serializer.validated_data)
        validated_data.pop("school", None)

        school = self.resolve_school(serializer.validated_data)

        try:
            teacher = create_teacher(
                school=school,
                validated_data=validated_data,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)
        except IntegrityError:
            raise ValidationError(
                {
                    "employee_id": (
                        "A teacher with this employee ID already "
                        "exists in this school."
                    )
                }
            )

        return created_response(
            "Teacher created successfully. "
            "Activate the teacher to email their login details.",
            TeacherDetailSerializer(teacher).data,
        )


class TeacherDetailAPIView(
    TeacherBaseMixin,
    generics.GenericAPIView,
):
    """Retrieve, update, and delete a teacher."""

    permission_classes = [
        IsAuthenticated,
        IsSuperOrSchoolAdmin,
    ]

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return TeacherUpdateSerializer

        return TeacherDetailSerializer

    def get(self, request, pk, *args, **kwargs):
        teacher = self.get_teacher_or_404(pk)

        return success_response(
            "Teacher fetched successfully.",
            TeacherDetailSerializer(teacher).data,
        )

    def patch(self, request, pk, *args, **kwargs):
        teacher = self.get_teacher_or_404(pk)

        serializer = self.get_serializer(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        try:
            teacher = update_teacher(
                teacher=teacher,
                validated_data=serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)
        except IntegrityError:
            raise ValidationError(
                {
                    "employee_id": (
                        "A teacher with this employee ID already "
                        "exists in this school."
                    )
                }
            )

        return updated_response(
            "Teacher updated successfully.",
            TeacherDetailSerializer(teacher).data,
        )

    def put(self, request, pk, *args, **kwargs):
        return self.patch(request, pk, *args, **kwargs)

    def delete(self, request, pk, *args, **kwargs):
        teacher = self.get_teacher_or_404(pk)

        try:
            delete_teacher(teacher=teacher)
        except IntegrityError:
            return error_response(
                "Teacher cannot be deleted because they are "
                "referenced by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response("Teacher deleted successfully.")


class TeacherBulkUploadAPIView(
    TeacherBaseMixin,
    generics.GenericAPIView,
):
    """
    Create teachers in bulk from a CSV file.

    The file is validated in full before anything is written, so a
    single bad row fails the whole upload and reports every problem at
    once.
    """

    permission_classes = [
        IsAuthenticated,
        IsSuperOrSchoolAdmin,
    ]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = TeacherBulkUploadSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        school = self.resolve_school(serializer.validated_data)

        try:
            result = import_teachers_from_csv(
                school=school,
                file_obj=serializer.validated_data["file"],
                row_serializer_class=TeacherCSVRowSerializer,
            )
        except CSVImportError as exc:
            return error_response(
                "CSV validation failed. No teachers were created.",
                exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)

        return created_response(
            f"{result['created']} teacher(s) created successfully. "
            "Activate them to email their login details.",
            {
                "created": result["created"],
                "teachers": TeacherListSerializer(
                    result["teachers"],
                    many=True,
                ).data,
            },
        )


class TeacherStatusAPIView(
    TeacherBaseMixin,
    generics.GenericAPIView,
):
    """
    Activate or deactivate a teacher.

    Activation generates a fresh password and emails it along with the
    login address.
    """

    permission_classes = [
        IsAuthenticated,
        IsSuperOrSchoolAdmin,
    ]
    serializer_class = TeacherStatusSerializer

    def patch(self, request, pk, *args, **kwargs):
        teacher = self.get_teacher_or_404(pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        is_active = serializer.validated_data["is_active"]

        changed = set_teacher_status(
            teacher=teacher,
            is_active=is_active,
            changed_by=request.user,
        )

        action = "activated" if is_active else "deactivated"

        if changed and is_active:
            message = (
                "Teacher activated successfully. "
                "Login details have been emailed to them."
            )
        elif changed:
            message = "Teacher deactivated successfully."
        else:
            message = f"Teacher is already {action}."

        teacher.refresh_from_db()

        return updated_response(
            message,
            TeacherDetailSerializer(teacher).data,
        )

    def post(self, request, pk, *args, **kwargs):
        return self.patch(request, pk, *args, **kwargs)


class TeacherAssignmentAPIView(
    TeacherBaseMixin,
    generics.GenericAPIView,
):
    """
    Assign or revoke a teacher's class-section.

    A teacher holds one class-section at a time, so assigning replaces
    any existing assignment.
    """

    permission_classes = [
        IsAuthenticated,
        IsSuperOrSchoolAdmin,
    ]
    serializer_class = ClassSectionAssignmentSerializer

    def post(self, request, pk, *args, **kwargs):
        teacher = self.get_teacher_or_404(pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            teacher = assign_class_section(
                teacher=teacher,
                class_section=serializer.validated_data["class_section"],
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)

        return updated_response(
            "Class section assigned successfully.",
            TeacherDetailSerializer(teacher).data,
        )

    def delete(self, request, pk, *args, **kwargs):
        teacher = self.get_teacher_or_404(pk)

        changed = revoke_class_section(teacher=teacher)

        if not changed:
            return error_response(
                "This teacher has no class section assigned.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return updated_response(
            "Class section revoked successfully.",
            TeacherDetailSerializer(teacher).data,
        )


class TeacherTransferAPIView(
    TeacherBaseMixin,
    generics.GenericAPIView,
):
    """
    Move a teacher from their current class-section to another.

    Unlike assignment, a transfer requires the teacher to hold a
    class-section already, so an accidental transfer cannot silently
    stand in for a first assignment.
    """

    permission_classes = [
        IsAuthenticated,
        IsSuperOrSchoolAdmin,
    ]
    serializer_class = ClassSectionAssignmentSerializer

    def post(self, request, pk, *args, **kwargs):
        teacher = self.get_teacher_or_404(pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        class_section = serializer.validated_data["class_section"]

        if teacher.class_section_id is None:
            return error_response(
                "This teacher has no class section to transfer from. "
                "Assign one instead.",
                status_code=status.HTTP_409_CONFLICT,
            )

        if teacher.class_section_id == class_section.id:
            return error_response(
                "The teacher is already assigned to this class "
                "section.",
                status_code=status.HTTP_409_CONFLICT,
            )

        try:
            teacher, previous = transfer_class_section(
                teacher=teacher,
                class_section=class_section,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)

        return updated_response(
            "Teacher transferred successfully.",
            {
                "transferred_from": previous.id,
                "teacher": TeacherDetailSerializer(teacher).data,
            },
        )


class TeacherMeAPIView(generics.GenericAPIView):
    """The authenticated teacher's own record."""

    permission_classes = [
        IsAuthenticated,
        IsTeacher,
    ]
    serializer_class = TeacherProfileSerializer

    def get(self, request, *args, **kwargs):
        try:
            teacher = get_teacher_profile(request.user)
        except DatabaseError:
            logger.exception(
                "Teacher profile lookup failed for user=%s. The "
                "teachers schema is probably out of date - check for "
                "unapplied migrations.",
                request.user.pk,
            )
            teacher = None

        if teacher is None:
            return not_found_response(
                "No teacher profile is linked to this account.",
            )

        return success_response(
            "Teacher profile fetched successfully.",
            self.get_serializer(teacher).data,
        )
