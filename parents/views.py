"""Parent API views: staff management and the parent portal."""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters import rest_framework as django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from accounts.authentication import set_token_cookie
from accounts.serializers import UserSerializer
from accounts.services import login_user
from attendance_student.serializers import AIJobSerializer
from attendance_student.services import has_registered_face, start_student_photo_job
from common.choices import AttendanceStatus
from common.csv_import import CSVImportError
from common.ordering import NaturalOrderingFilter
from common.pagination import StandardResultsPagination
from common.throttling import LOGIN_THROTTLES
from common.permissions import IsParent, IsParentManager
from common.responses import (
    created_response,
    deleted_response,
    error_response,
    success_response,
    updated_response,
)
from students.selectors import get_students_visible_to
from students.serializers import StudentDetailSerializer, StudentProfileImageSerializer
from students.services import update_student_profile_image

from . import services
from .selectors import (
    PARENT_ORDERING,
    get_children_attendance,
    get_notifications,
    get_own_parent,
    get_parent,
    get_parents_visible_to,
)
from .csv_import import import_parents_from_csv
from .serializers import (
    ChildAttendanceSerializer,
    MarkReadSerializer,
    ParentBulkUploadSerializer,
    ParentCSVRowSerializer,
    ParentCreateSerializer,
    ParentLoginSerializer,
    ParentNotificationSerializer,
    ParentProfileSerializer,
    ParentSerializer,
    ParentUpdateSerializer,
)


def to_drf_error(exc: DjangoValidationError) -> ValidationError:
    if hasattr(exc, "error_dict"):
        return ValidationError(exc.message_dict)

    return ValidationError({"detail": exc.messages})


class ParentLoginAPIView(generics.GenericAPIView):
    """
    Parents sign in with their mobile number and password. Tokens are
    set as the same cookies the staff login uses, and
    ``must_change_password`` prompts the parent to replace the password
    staff gave out.
    """

    serializer_class = ParentLoginSerializer
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = LOGIN_THROTTLES

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return error_response(
                "Invalid credentials.",
                serializer.errors,
                status.HTTP_400_BAD_REQUEST,
            )

        parent = services.find_parent_by_phone(serializer.validated_data["phone_number"])
        user = parent.user if parent else None

        if user is None or not user.check_password(serializer.validated_data["password"]):
            return error_response(
                "Invalid credentials.",
                {"non_field_errors": ["Invalid mobile number or password."]},
                status.HTTP_400_BAD_REQUEST,
            )

        if not user.is_active:
            return error_response(
                "Invalid credentials.",
                {"non_field_errors": ["This account is inactive."]},
                status.HTTP_400_BAD_REQUEST,
            )

        result = login_user(user)

        response = success_response(
            "Login successful.",
            {
                "user": UserSerializer(result["user"]).data,
                "must_change_password": not parent.password_changed,
            },
        )
        set_token_cookie(response, settings.JWT_ACCESS_COOKIE, result["tokens"]["access"])
        set_token_cookie(response, settings.JWT_REFRESH_COOKIE, result["tokens"]["refresh"])

        return response


class ParentBaseMixin:
    permission_classes = [IsAuthenticated, IsParentManager]

    def get_parent_or_404(self, pk):
        parent = get_parent(pk, actor=self.request.user)

        if parent is None:
            raise NotFound("Parent not found.")

        return parent


class ParentListCreateAPIView(ParentBaseMixin, generics.ListCreateAPIView):
    """List parents in scope, or create one for a student."""

    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, NaturalOrderingFilter]
    search_fields = [
        "user__name",
        "user__phone_number",
        "students__student_id",
        "students__name",
    ]
    ordering_fields = ["user__name", "created_at", "roll_number"]
    ordering = PARENT_ORDERING

    def get_queryset(self):
        queryset = get_parents_visible_to(self.request.user)

        for param, field in (
            ("student", "students__id"),
            ("class_section", "students__class_section_id"),
            ("school", "students__school_id"),
        ):
            value = self.request.query_params.get(param)

            if value:
                if not value.isdigit():
                    raise ValidationError({param: "Must be a number."})

                queryset = queryset.filter(**{field: value})

        return queryset

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ParentCreateSerializer

        return ParentSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(ParentSerializer(page, many=True).data)

        return success_response(
            "Parents fetched successfully.",
            ParentSerializer(queryset, many=True).data,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        students = get_students_visible_to(request.user).filter(
            student_id=data["student_id"],
        )

        if data.get("school") is not None:
            students = students.filter(school=data["school"])

        student = students.first()

        if student is None:
            raise ValidationError(
                {"student_id": "No student with this ID in your scope."}
            )

        try:
            parent, created = services.create_or_link_parent(
                name=data["name"],
                phone_number=data["phone_number"],
                student=student,
                actor=request.user,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        parent = self.get_parent_or_404(parent.pk)

        if created:
            message = "Parent created successfully."
        else:
            message = (
                f"A parent with this mobile number already exists "
                f"({parent.user.name}); student {student.student_id} "
                "was linked to them."
            )

        response_data = {"created": created, **ParentSerializer(parent).data}

        if created:
            return created_response(message, response_data)

        return success_response(message, response_data)


class ParentBulkUploadAPIView(ParentBaseMixin, generics.GenericAPIView):
    """
    Create or link parents in bulk from a CSV of
    ``student_id, name, phone_number`` (one row per child).

    Works like adding parents one by one: a mobile number that already
    belongs to a parent links the child to that account instead of
    creating another, and a parent with several children appears once
    per child. Teachers can name only their own class's students, School
    Admins their school's, and Super Admins pick the school.

    The file is validated in full before anything is written, so one bad
    row fails the upload and every problem is reported at once. New parents
    come back with their generated password, for staff to share.
    """

    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ParentBulkUploadSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        students = get_students_visible_to(request.user)

        if data.get("school") is not None:
            students = students.filter(school=data["school"])

        try:
            result = import_parents_from_csv(
                file_obj=data["file"],
                students_queryset=students,
                row_serializer_class=ParentCSVRowSerializer,
                actor=request.user,
            )
        except CSVImportError as exc:
            return error_response(
                "CSV validation failed. No parents were added.",
                exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        rows = result["rows"]
        created = sum(1 for r in rows if r["created"])
        linked = sum(1 for r in rows if not r["created"] and not r["already_linked"])
        unchanged = sum(1 for r in rows if r["already_linked"])

        parents = {p.pk: p for p in get_parents_visible_to(request.user).filter(pk__in=result["parent_ids"])}

        return created_response(
            f"{created} parent(s) created, {linked} child link(s) added to existing parents"
            + (f", {unchanged} already linked" if unchanged else "")
            + ".",
            {
                "created": created,
                "linked": linked,
                "already_linked": unchanged,
                "rows": rows,
                "parents": ParentSerializer(
                    [parents[pk] for pk in result["parent_ids"] if pk in parents],
                    many=True,
                ).data,
            },
        )


class ParentDetailAPIView(ParentBaseMixin, generics.GenericAPIView):
    serializer_class = ParentUpdateSerializer

    def get(self, request, pk, *args, **kwargs):
        return success_response(
            "Parent fetched successfully.",
            ParentSerializer(self.get_parent_or_404(pk)).data,
        )

    def patch(self, request, pk, *args, **kwargs):
        parent = self.get_parent_or_404(pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            services.update_parent(parent=parent, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return updated_response(
            "Parent updated successfully.",
            ParentSerializer(self.get_parent_or_404(pk)).data,
        )

    def put(self, request, pk, *args, **kwargs):
        return self.patch(request, pk, *args, **kwargs)


class ParentResetPasswordAPIView(ParentBaseMixin, generics.GenericAPIView):
    """Generate a new ``Firstname@1234`` password for a parent."""

    def post(self, request, pk, *args, **kwargs):
        parent = self.get_parent_or_404(pk)
        services.reset_parent_password(parent=parent, actor=request.user)

        return updated_response(
            "Parent password reset successfully.",
            ParentSerializer(self.get_parent_or_404(pk)).data,
        )


class ParentStudentUnlinkAPIView(ParentBaseMixin, generics.GenericAPIView):
    """
    Unlink a child from a parent. The parent account is deleted when
    no children remain.
    """

    def delete(self, request, pk, student_pk, *args, **kwargs):
        parent = self.get_parent_or_404(pk)
        student = next(
            (s for s in parent.students.all() if s.pk == student_pk),
            None,
        )

        if student is None:
            raise NotFound("This student is not linked to the parent.")

        deleted = services.unlink_student(parent=parent, student=student)

        return deleted_response(
            "Student unlinked; the parent had no other children and was deleted."
            if deleted
            else "Student unlinked from the parent.",
            {"parent_deleted": deleted},
        )


class ParentPortalMixin:
    permission_classes = [IsAuthenticated, IsParent]

    def get_own_parent(self):
        parent = get_own_parent(self.request.user)

        if parent is None:
            raise NotFound("No parent profile is linked to your account.")

        return parent


class MyProfileAPIView(ParentPortalMixin, generics.GenericAPIView):
    def get(self, request, *args, **kwargs):
        return success_response(
            "Profile fetched successfully.",
            ParentProfileSerializer(self.get_own_parent()).data,
        )


class ChildAttendanceFilter(django_filters.FilterSet):
    student = django_filters.NumberFilter(field_name="student_id")
    date = django_filters.DateFilter(field_name="session__date")
    date_from = django_filters.DateFilter(field_name="session__date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="session__date", lookup_expr="lte")
    status = django_filters.ChoiceFilter(choices=AttendanceStatus.choices)


class MyChildrenAttendanceAPIView(ParentPortalMixin, generics.ListAPIView):
    """Daily, finalised attendance of the parent's children."""

    serializer_class = ChildAttendanceSerializer
    pagination_class = StandardResultsPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ChildAttendanceFilter

    def get_queryset(self):
        return get_children_attendance(self.get_own_parent())

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)

        return success_response(
            "Attendance fetched successfully.",
            self.get_serializer(queryset, many=True).data,
        )


class MyNotificationsAPIView(ParentPortalMixin, generics.ListAPIView):
    """
    Attendance notifications, newest first. ``?is_read=false`` for
    unread only.
    """

    serializer_class = ParentNotificationSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        queryset = get_notifications(self.get_own_parent())
        is_read = self.request.query_params.get("is_read")

        if is_read in ("true", "false"):
            queryset = queryset.filter(is_read=is_read == "true")

        return queryset

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())

        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)

        return success_response(
            "Notifications fetched successfully.",
            self.get_serializer(self.get_queryset(), many=True).data,
        )


class MyUnreadCountAPIView(ParentPortalMixin, generics.GenericAPIView):
    def get(self, request, *args, **kwargs):
        parent = self.get_own_parent()

        return success_response(
            "Unread count fetched successfully.",
            {"unread": parent.notifications.filter(is_read=False).count()},
        )


class MyNotificationsReadAPIView(ParentPortalMixin, generics.GenericAPIView):
    """Mark notifications read: the given ``ids``, or all of them."""

    serializer_class = MarkReadSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.mark_notifications_read(
            parent=self.get_own_parent(),
            ids=serializer.validated_data.get("ids"),
        )

        return updated_response(
            f"{updated} notification(s) marked as read.",
            {"updated": updated},
        )


class MyChildPhotoAPIView(ParentPortalMixin, generics.GenericAPIView):
    """
    A parent uploads or changes their child's photo.

    The first photo (no face registered yet) is only saved; registering
    the face from it stays with the school's staff. Once the school has
    registered a face, a new photo replaces it and is registered straight
    away, exactly as when staff change the photo: one the AI service
    rejects (no face, several faces...) is refused and the old one kept.
    That registration runs in the background; ``face_job`` in the
    answer is the job to poll (null when only the photo was saved).
    """

    parser_classes = [MultiPartParser, FormParser]
    serializer_class = StudentProfileImageSerializer

    def post(self, request, student_pk, *args, **kwargs):
        parent = self.get_own_parent()
        student = next((s for s in parent.students.all() if s.pk == student_pk), None)

        if student is None:
            raise NotFound("This student is not linked to your account.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = serializer.validated_data["profile_image"]

        face_job = None

        if not has_registered_face(student):
            update_student_profile_image(student=student, image=photo)
            message = "Photo uploaded. The school will register your child's face from it."
        else:
            face_job = start_student_photo_job(student=student, image_file=photo, actor=request.user)
            message = (
                "Photo received. It is being checked and your child's face "
                "registered from it; this can take a few minutes."
            )

        student.refresh_from_db()
        data = StudentDetailSerializer(student).data
        data["face_job"] = AIJobSerializer(face_job).data if face_job else None

        return updated_response(message, data)

    def patch(self, request, student_pk, *args, **kwargs):
        return self.post(request, student_pk, *args, **kwargs)
