"""Face registration and student attendance API views."""

import logging
from collections import Counter
from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from common.choices import AttendanceStatus
from common.ordering import roll_order
from common.pagination import StandardResultsPagination
from common.permissions import IsAttendanceManager, IsSuperOrSchoolAdmin
from common.choices import UserRole
from common.responses import (
    accepted_response,
    created_response,
    deleted_response,
    error_response,
    success_response,
    updated_response,
)
from students.selectors import get_class_sections_visible_to
from students.views import StudentBaseMixin

from . import services
from .ai_client import AIServiceError
from .attendance_filters import AttendanceSessionFilter
from .jobs import expire_if_stale
from .models import AIJob, AIJobKind
from .selectors import (
    get_face_students_visible_to,
    get_session,
    get_sessions_visible_to,
)
from .serializers import (
    AIJobSerializer,
    AttendanceSessionDetailSerializer,
    AttendanceSessionListSerializer,
    FaceRegisterFromProfileSerializer,
    FaceRegisterSerializer,
    FaceScopeSerializer,
    FaceStatusSerializer,
    ManualSessionCreateSerializer,
    RecordsUpdateSerializer,
    VerifyAttendanceSerializer,
)

logger = logging.getLogger(__name__)


def to_drf_error(exc: DjangoValidationError) -> ValidationError:
    if hasattr(exc, "error_dict"):
        return ValidationError(exc.message_dict)

    return ValidationError({"detail": exc.messages})


def ai_error_response(exc: AIServiceError):
    return error_response(
        exc.message,
        {"ai_service": exc.message},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def job_response(message: str, job: AIJob):
    """
    202 with the queued job; the client polls ``jobs/<id>/`` for it.
    """

    return accepted_response(message, AIJobSerializer(job).data)


def nothing_registered_response(rejected):
    return error_response(
        "No faces were registered.",
        services.registration_summary(rejected),
        status_code=status.HTTP_400_BAD_REQUEST,
    )


class AttendanceBaseMixin(StudentBaseMixin):
    """
    Shared scoping helpers.

    ``resolve_class_section`` is inherited from the students app so the
    rules for "which class-section does this caller mean" are the same
    everywhere: a teacher always gets their own, admins name one they
    can see.
    """

    permission_classes = [
        IsAuthenticated,
        IsAttendanceManager,
    ]

    def get_session_or_404(self, pk, *, with_records=False):
        session = get_session(
            pk,
            actor=self.request.user,
            with_records=with_records,
        )

        if session is None:
            raise NotFound("Attendance not found.")

        return session

    def detail_data(self, session):
        session = self.get_session_or_404(session.pk, with_records=True)
        return AttendanceSessionDetailSerializer(session).data

    def get_face_scope(self, validated_data):
        """
        Students whose faces the caller may manage, narrowed by the
        optional school / class-section they named.
        """

        user = self.request.user
        queryset = get_face_students_visible_to(user)

        school = validated_data.get("school")
        class_section = validated_data.get("class_section")

        if school is not None:
            queryset = queryset.filter(school=school)

        if class_section is not None:
            visible = get_class_sections_visible_to(user).filter(
                pk=class_section.pk,
            )

            if not visible.exists() or (
                school is not None
                and class_section.academic_year.school_id != school.id
            ):
                raise ValidationError(
                    {
                        "class_section": (
                            "The class section is outside the school(s) "
                            "you can manage."
                        )
                    }
                )

            queryset = queryset.filter(class_section=class_section)

        return queryset


class FaceListAPIView(AttendanceBaseMixin, generics.GenericAPIView):
    """
    Students in scope with their face-registration status.

    Query params: ``school`` (Super Admin, required), ``class_section``
    (admins), ``registered`` (true/false), ``search``.
    """

    pagination_class = StandardResultsPagination
    serializer_class = FaceStatusSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "student_id", "roll_number"]

    def get(self, request, *args, **kwargs):
        params = FaceScopeSerializer(
            data=request.query_params,
            context={"request": request},
        )
        params.is_valid(raise_exception=True)

        queryset = self.get_face_scope(params.validated_data).order_by(
            "class_section",
            roll_order(),
        )

        registered = params.validated_data.get("registered")

        if registered is not None:
            queryset = queryset.filter(
                face_registration__isnull=not registered,
            )

        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                FaceStatusSerializer(page, many=True).data,
            )

        return success_response(
            "Face registrations fetched successfully.",
            FaceStatusSerializer(queryset, many=True).data,
        )


class FaceRegisterAPIView(AttendanceBaseMixin, generics.GenericAPIView):
    """
    Upload images and register them as faces.

    Bulk: send many ``images``, each named after the student ID
    (``STU001.jpg``). Single: send one image plus ``student`` (the
    student's primary key) to register regardless of file name.

    Each uploaded image also becomes the student's profile image.

    Registration runs in the background: the answer is 202 with a job
    to poll, whose result is the per-file summary. Files that cannot
    match a student are part of that summary; if none can, the request
    is refused straight away with 400 and the summary.
    """

    parser_classes = [MultiPartParser, FormParser]
    serializer_class = FaceRegisterSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        scope = self.get_face_scope(data)
        images = data["images"]

        if data.get("student") is not None:
            student = scope.filter(pk=data["student"].pk).first()

            if student is None:
                raise NotFound("Student not found.")

            items, rejected = [(images[0].name, student, images[0])], []
        else:
            items, rejected = self._match_files_to_students(scope, images)

        unknown = [
            {
                "label": label,
                "student": None,
                "student_id": Path(label).stem.strip().upper(),
                "registered": False,
                "error": "Student not found in your scope.",
            }
            for label, student, _ in items
            if student is None
        ]
        rejected += unknown
        items = [item for item in items if item[1] is not None]

        if not items:
            return nothing_registered_response(rejected)

        job = services.start_face_registration_job(
            kind=AIJobKind.FACE_REGISTER,
            items=items,
            rejected=rejected,
            actor=request.user,
        )

        return job_response(
            f"Registering {len(items)} face(s) in the background. "
            "Follow the job for progress.",
            job,
        )

    @staticmethod
    def _match_files_to_students(scope, images):
        """
        Pair each file with the student its name names. Files sharing a
        student ID are rejected, never guessing which photo is right.
        """

        keys = [Path(image.name).stem.strip().upper() for image in images]
        counts = Counter(keys)
        students = {
            student.student_id: student
            for student in scope.filter(student_id__in=set(keys))
        }

        items = []
        rejected = []

        for key, image in zip(keys, images):
            if counts[key] > 1:
                rejected.append(
                    {
                        "label": image.name,
                        "student": None,
                        "student_id": key,
                        "registered": False,
                        "error": "Several files share this student ID.",
                    }
                )
                continue

            items.append((image.name, students.get(key), image))

        return items, rejected


class FaceRegisterFromProfileAPIView(
    AttendanceBaseMixin,
    generics.GenericAPIView,
):
    """
    Register faces from profile images already uploaded through the
    students app, so nothing has to be uploaded twice.

    Like uploads, this answers 202 with a job to poll.
    """

    parser_classes = [JSONParser, MultiPartParser, FormParser]
    serializer_class = FaceRegisterFromProfileSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        scope = self.get_face_scope(data)
        requested = data.get("students")

        if requested:
            requested_ids = [student.pk for student in requested]
            found = {s.pk: s for s in scope.filter(pk__in=requested_ids)}
            items = [
                (str(pk), found.get(pk), None)
                for pk in requested_ids
            ]
        else:
            queryset = scope.exclude(
                Q(profile_image="") | Q(profile_image__isnull=True),
            )
            items = [(s.student_id, s, None) for s in queryset]

        if data["only_unregistered"]:
            items = [
                item for item in items
                if item[1] is None
                or not services.has_registered_face(item[1])
            ]

        if not items:
            return success_response(
                "Nothing to register: every selected student already "
                "has a face or has no profile image.",
                services.registration_summary([]),
            )

        rejected = [
            {
                "label": label,
                "student": None,
                "student_id": None,
                "registered": False,
                "error": "Student not found in your scope.",
            }
            for label, student, _ in items
            if student is None
        ]
        items = [item for item in items if item[1] is not None]

        if not items:
            return nothing_registered_response(rejected)

        job = services.start_face_registration_job(
            kind=AIJobKind.FACE_REGISTER_FROM_PROFILE,
            items=items,
            rejected=rejected,
            actor=request.user,
        )

        return job_response(
            f"Registering {len(items)} face(s) from profile images in the "
            "background. Follow the job for progress.",
            job,
        )


class FaceDeleteAPIView(AttendanceBaseMixin, generics.GenericAPIView):
    """
    Delete a student's registered face from the AI service.

    Faces are also deleted automatically when a student's profile image
    or student ID changes, or the student is deleted.
    """

    def delete(self, request, student_pk, *args, **kwargs):
        student = get_face_students_visible_to(request.user).filter(
            pk=student_pk,
        ).first()

        if student is None:
            raise NotFound("Student not found.")

        try:
            existed = services.delete_face_for_student(student=student)
        except AIServiceError as exc:
            return ai_error_response(exc)

        return deleted_response(
            "Face deleted successfully."
            if existed
            else "No face was registered for this student.",
            {"student": student.pk, "student_id": student.student_id},
        )


class AttendanceVerifyAPIView(AttendanceBaseMixin, generics.GenericAPIView):
    """
    Upload classroom photos and let the AI mark attendance.

    The result is saved as a DRAFT for the class-section and date,
    which the teacher can then correct and lock.

    The request is checked at once (date, lock, registered faces), then
    recognition runs in the background: the answer is 202 with a job
    to poll, whose result is ``{"session": <id>}``.
    """

    parser_classes = [MultiPartParser, FormParser]
    serializer_class = VerifyAttendanceSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        class_section = self.resolve_class_section(serializer.validated_data)

        try:
            job = services.start_verification_job(
                class_section=class_section,
                date=serializer.validated_data["date"],
                image_files=serializer.validated_data["images"],
                actor=request.user,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return job_response(
            "Photos received. Recognising faces in the background; "
            "follow the job for progress.",
            job,
        )


class AIJobDetailAPIView(generics.GenericAPIView):
    """
    Poll a background AI job started by the caller.

    Open to every signed-in role (parents start photo jobs too); each
    user sees only their own jobs, Super Admins see all.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        jobs = AIJob.objects.all()
        user = request.user

        if not (user.is_superuser or user.role == UserRole.SUPER_ADMIN):
            jobs = jobs.filter(created_by=user)

        job = jobs.filter(pk=pk).first()

        if job is None:
            raise NotFound("Job not found.")

        job = expire_if_stale(job)

        return success_response(
            job.message or "Job fetched successfully.",
            AIJobSerializer(job).data,
        )


class AttendanceSessionListCreateAPIView(
    AttendanceBaseMixin,
    generics.ListCreateAPIView,
):
    """
    List attendance, or start one by hand without photos.
    """

    pagination_class = StandardResultsPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.OrderingFilter,
    ]
    filterset_class = AttendanceSessionFilter
    ordering_fields = ["date", "created_at", "status"]
    ordering = ["-date", "class_section"]

    def get_queryset(self):
        return get_sessions_visible_to(self.request.user).annotate(
            total_students=Count("records"),
            present_count=Count(
                "records",
                filter=Q(records__status=AttendanceStatus.PRESENT),
            ),
            absent_count=Count(
                "records",
                filter=Q(records__status=AttendanceStatus.ABSENT),
            ),
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ManualSessionCreateSerializer

        return AttendanceSessionListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        return success_response(
            "Attendance fetched successfully.",
            self.get_serializer(queryset, many=True).data,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        class_section = self.resolve_class_section(serializer.validated_data)

        try:
            session = services.create_manual_session(
                class_section=class_section,
                date=serializer.validated_data["date"],
                actor=request.user,
                records=serializer.validated_data.get("records"),
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return created_response(
            "Attendance created as draft.",
            self.detail_data(session),
        )


class AttendanceSessionDetailAPIView(
    AttendanceBaseMixin,
    generics.GenericAPIView,
):
    """
    Read an attendance, or delete it with all its records.

    Only admins may delete, whether the attendance is locked or not.
    """

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated(), IsSuperOrSchoolAdmin()]

        return super().get_permissions()

    def get(self, request, pk, *args, **kwargs):
        session = self.get_session_or_404(pk, with_records=True)
        return success_response(
            "Attendance fetched successfully.",
            AttendanceSessionDetailSerializer(session).data,
        )

    def delete(self, request, pk, *args, **kwargs):
        session = self.get_session_or_404(pk)
        data = {
            "id": session.pk,
            "class_section": session.class_section_id,
            "date": session.date,
        }

        services.delete_session(session=session, actor=request.user)

        return deleted_response("Attendance deleted successfully.", data)


class AttendanceRecordsUpdateAPIView(
    AttendanceBaseMixin,
    generics.GenericAPIView,
):
    """
    Correct students' statuses.

    Teachers can do this only while the attendance is a draft; admins
    can do it at any time.
    """

    serializer_class = RecordsUpdateSerializer

    def patch(self, request, pk, *args, **kwargs):
        session = self.get_session_or_404(pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            session = services.update_records(
                session=session,
                actor=request.user,
                records=serializer.validated_data["records"],
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return updated_response(
            "Attendance updated successfully.",
            self.detail_data(session),
        )

    def put(self, request, pk, *args, **kwargs):
        return self.patch(request, pk, *args, **kwargs)


class AttendanceLockAPIView(AttendanceBaseMixin, generics.GenericAPIView):
    """
    Finalise a draft. After this only admins can change it.
    """

    def post(self, request, pk, *args, **kwargs):
        session = self.get_session_or_404(pk)
        session = services.lock_session(session=session, actor=request.user)

        return updated_response(
            "Attendance locked successfully.",
            self.detail_data(session),
        )


class AttendanceUnlockAPIView(AttendanceBaseMixin, generics.GenericAPIView):
    """
    Return a locked attendance to draft so the teacher can edit it.
    """

    permission_classes = [
        IsAuthenticated,
        IsSuperOrSchoolAdmin,
    ]

    def post(self, request, pk, *args, **kwargs):
        session = self.get_session_or_404(pk)

        try:
            session = services.unlock_session(session=session, actor=request.user)
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return updated_response(
            "Attendance unlocked successfully.",
            self.detail_data(session),
        )
