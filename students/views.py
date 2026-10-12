"""Student API views."""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from attendance_student.models import AIJobStatus
from attendance_student.serializers import AIJobSerializer
from attendance_student.services import start_student_photo_job
from common.choices import UserRole
from common.ordering import NaturalOrderingFilter
from common.pagination import StandardResultsPagination
from common.csv_import import CSVImportError
from common.permissions import IsStudentManager, IsSuperOrSchoolAdmin
from common.responses import (
    accepted_response,
    created_response,
    deleted_response,
    error_response,
    success_response,
    updated_response,
)

from .csv_import import import_students_from_csv
from .selectors import (
    get_actor_class_section,
    get_class_sections_visible_to,
    get_student,
    get_students_visible_to,
    is_super_admin,
)
from .serializers import (
    StudentBulkUploadSerializer,
    StudentCreateSerializer,
    StudentCSVRowSerializer,
    StudentDetailSerializer,
    StudentListSerializer,
    StudentProfileImageSerializer,
    StudentPromoteSerializer,
    StudentUpdateSerializer,
)
from .services import (
    create_student,
    delete_student,
    promote_students,
    update_student,
)
from .student_filters import StudentFilter

logger = logging.getLogger(__name__)


def photo_message(message: str, face_job) -> str:
    """``message`` plus where the photo's face registration stands."""

    if face_job is None:
        return message

    if face_job.is_active:
        return (
            f"{message} The photo is being checked and registered as the "
            "face in the background; this can take a few minutes."
        )

    if face_job.status == AIJobStatus.FAILED:
        return f"{message} The photo was not saved: {face_job.error}"

    return f"{message} {face_job.message}"


def with_face_job(student, face_job) -> dict:
    """
    Student detail plus the photo's face-registration job, if any, for
    the client to poll. The student is reloaded because a job run inline
    (as in tests) has already changed it.
    """

    if face_job is not None:
        student.refresh_from_db()

    data = StudentDetailSerializer(student).data
    data["face_job"] = AIJobSerializer(face_job).data if face_job else None

    return data


class StudentBaseMixin:
    """Shared scoping helpers for student views."""

    def get_student_or_404(self, pk):
        """
        Fetch a student the actor is allowed to see.

        A student outside the actor's scope is reported as missing
        rather than forbidden, so a teacher cannot probe for students
        in other class-sections.
        """

        try:
            student = get_student(pk, actor=self.request.user)
        except DatabaseError:
            logger.exception(
                "Student lookup failed for pk=%s. The students schema "
                "is probably out of date - check for unapplied "
                "migrations.",
                pk,
            )
            raise NotFound("Student not found.")

        if student is None:
            raise NotFound("Student not found.")

        return student

    def resolve_class_section(self, validated_data, *, required=True):
        """
        Work out which class-section the caller means.

        Super Admins and School Admins name it; a teacher never does,
        because the section they are assigned to is the only one they
        may use. Whoever names it, it has to be one they can already
        see, so nobody can enrol a student somewhere they would then
        lose sight of them. A Super Admin also names the school, so the
        two must agree.
        """

        user = self.request.user

        if user.role == UserRole.TEACHER:
            class_section = get_actor_class_section(user)

            if class_section is None:
                raise ValidationError(
                    {
                        "detail": (
                            "You are not assigned to a class section, "
                            "so you cannot manage students yet."
                        )
                    }
                )

            return class_section

        class_section = validated_data.get("class_section")

        if class_section is None:
            if required:
                raise ValidationError(
                    {"class_section": "This field is required."},
                )

            return None

        allowed = get_class_sections_visible_to(user).filter(
            pk=class_section.pk,
        )

        if not allowed.exists():
            raise ValidationError(
                {
                    "class_section": (
                        "The class section does not belong to a "
                        "school you administer."
                    )
                }
            )

        if is_super_admin(user):
            school = validated_data.get("school")

            if (
                school is not None
                and class_section.academic_year.school_id != school.id
            ):
                raise ValidationError(
                    {
                        "class_section": (
                            "The class section does not belong to the "
                            "selected school."
                        )
                    }
                )

        return class_section


class StudentListCreateAPIView(
    StudentBaseMixin,
    generics.ListCreateAPIView,
):
    """
    List students and enrol new ones.

    Teachers work inside their own class-section; admins work across
    whichever schools they administer.
    """

    permission_classes = [
        IsAuthenticated,
        IsStudentManager,
    ]
    parser_classes = [
        MultiPartParser,
        FormParser,
        generics.ListCreateAPIView.parser_classes[0],
    ]
    pagination_class = StandardResultsPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        NaturalOrderingFilter,
    ]
    filterset_class = StudentFilter
    search_fields = [
        "name",
        "student_id",
        "roll_number",
    ]
    ordering_fields = [
        "roll_number",
        "student_id",
        "name",
        "created_at",
    ]
    ordering = ["class_section", "roll_number"]

    def get_queryset(self):
        return get_students_visible_to(self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StudentCreateSerializer

        return StudentListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        return success_response(
            "Students fetched successfully.",
            serializer.data,
        )

    def create(self, request, *args, **kwargs):
        """
        Enrol a student now; any photo follows in the background.

        The photo is saved through face registration, so the profile photo
        and the registered face are always the same one. That waits on the
        AI service, so it runs as a background job.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        class_section = self.resolve_class_section(
            serializer.validated_data,
        )

        payload = dict(serializer.validated_data)
        payload.pop("school", None)
        payload.pop("class_section", None)
        photo = payload.pop("profile_image", None)
        face_job = None

        try:
            with transaction.atomic():
                student = create_student(
                    class_section=class_section,
                    validated_data=payload,
                )

                if photo is not None:
                    face_job = start_student_photo_job(
                        student=student,
                        image_file=photo,
                        actor=request.user,
                    )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)
        except IntegrityError:
            raise ValidationError(
                {
                    "detail": (
                        "This student ID or roll number is already "
                        "taken."
                    )
                }
            )

        return created_response(
            photo_message("Student enrolled successfully.", face_job),
            with_face_job(student, face_job),
        )


class StudentDetailAPIView(
    StudentBaseMixin,
    generics.GenericAPIView,
):
    """Retrieve, update, and delete a student."""

    permission_classes = [
        IsAuthenticated,
        IsStudentManager,
    ]

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return StudentUpdateSerializer

        return StudentDetailSerializer

    def get(self, request, pk, *args, **kwargs):
        student = self.get_student_or_404(pk)

        return success_response(
            "Student fetched successfully.",
            StudentDetailSerializer(student).data,
        )

    def patch(self, request, pk, *args, **kwargs):
        student = self.get_student_or_404(pk)

        serializer = self.get_serializer(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        payload = dict(serializer.validated_data)
        payload.pop("school", None)
        requested_section = payload.pop("class_section", None)

        class_section = None

        if requested_section is not None:
            class_section = self.resolve_class_section(
                serializer.validated_data,
                required=False,
            )

        try:
            student = update_student(
                student=student,
                validated_data=payload,
                class_section=class_section,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)
        except IntegrityError:
            raise ValidationError(
                {
                    "detail": (
                        "This student ID or roll number is already "
                        "taken."
                    )
                }
            )

        return updated_response(
            "Student updated successfully.",
            StudentDetailSerializer(student).data,
        )

    def put(self, request, pk, *args, **kwargs):
        return self.patch(request, pk, *args, **kwargs)

    def delete(self, request, pk, *args, **kwargs):
        student = self.get_student_or_404(pk)

        try:
            delete_student(student=student)
        except IntegrityError:
            return error_response(
                "Student cannot be deleted because they are "
                "referenced by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response("Student deleted successfully.")


class StudentProfileImageAPIView(
    StudentBaseMixin,
    generics.GenericAPIView,
):
    """
    Upload or replace a student's profile image.

    The profile image is the only photo a face is registered from, so a
    new one is registered as the student's face at the same time. A
    photo the AI service rejects is refused and the old one is kept.

    Registration waits on the AI service, so it runs in the background:
    the answer is 202 with the student (still showing the old photo)
    and ``face_job`` to poll. The new photo is saved once accepted.
    """

    permission_classes = [
        IsAuthenticated,
        IsStudentManager,
    ]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = StudentProfileImageSerializer

    def patch(self, request, pk, *args, **kwargs):
        student = self.get_student_or_404(pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        face_job = start_student_photo_job(
            student=student,
            image_file=serializer.validated_data["profile_image"],
            actor=request.user,
        )

        return accepted_response(
            photo_message("Photo received.", face_job),
            with_face_job(student, face_job),
        )

    def post(self, request, pk, *args, **kwargs):
        return self.patch(request, pk, *args, **kwargs)


class StudentBulkUploadAPIView(
    StudentBaseMixin,
    generics.GenericAPIView,
):
    """
    Enrol students in bulk from a CSV file.

    Every row lands in one class-section, chosen the same way a single
    enrolment chooses it: teachers get their own, School Admins name
    one in their school, Super Admins name a school and a section.

    The file is validated in full before anything is written, so a
    single bad row fails the whole upload and reports every problem at
    once.
    """

    permission_classes = [
        IsAuthenticated,
        IsStudentManager,
    ]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = StudentBulkUploadSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        class_section = self.resolve_class_section(
            serializer.validated_data,
        )

        try:
            result = import_students_from_csv(
                class_section=class_section,
                file_obj=serializer.validated_data["file"],
                row_serializer_class=StudentCSVRowSerializer,
            )
        except CSVImportError as exc:
            return error_response(
                "CSV validation failed. No students were enrolled.",
                exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)

        return created_response(
            f"{result['created']} student(s) enrolled successfully.",
            {
                "created": result["created"],
                "class_section": class_section.id,
                "students": StudentListSerializer(
                    result["students"],
                    many=True,
                ).data,
            },
        )


class StudentPromoteAPIView(StudentBaseMixin, generics.GenericAPIView):
    """
    Promote students: move them, together, into another class-section
    (usually the next class in the next academic year), keeping or
    renumbering their roll numbers. School Admins and Super Admins only.
    """

    permission_classes = [IsAuthenticated, IsSuperOrSchoolAdmin]
    serializer_class = StudentPromoteSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ids = set(data["student_ids"])
        students = get_students_visible_to(request.user).filter(pk__in=ids)

        if students.count() != len(ids):
            raise ValidationError({"student_ids": "Some of these students were not found."})

        to_class_section = get_class_sections_visible_to(request.user).filter(pk=data["to_class_section"]).first()

        if to_class_section is None:
            raise ValidationError({"to_class_section": "Class section not found."})

        try:
            promoted = promote_students(
                students=students,
                to_class_section=to_class_section,
                roll_numbers=data["roll_numbers"],
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages})

        return updated_response(
            f"{len(promoted)} student(s) moved to {to_class_section}.",
            {"promoted": len(promoted), "to_class_section": to_class_section.pk},
        )
