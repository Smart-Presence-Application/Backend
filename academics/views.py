from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsSuperAdmin, IsAcademicAdmin
from common.responses import (
created_response,
deleted_response,
error_response,
paginated_response,
success_response,
updated_response,
)

from .academic_filters import (
AcademicYearFilter,
ClassSectionFilter,
HolidayFilter,
SchoolClassFilter,
SectionFilter,
WorkingDayFilter,
)
from .selectors import (
    get_academic_year_queryset,
    get_school_class_queryset,
    get_section_queryset,
    get_class_section_queryset,
    get_holiday_queryset,
    get_working_day_queryset,
)
from .serializers import (
AcademicYearCreateSerializer,
AcademicYearDetailSerializer,
AcademicYearListSerializer,
AcademicYearUpdateSerializer,
ClassSectionCreateSerializer,
ClassSectionDetailSerializer,
ClassSectionListSerializer,
ClassSectionUpdateSerializer,
HolidayCreateSerializer,
HolidayDetailSerializer,
HolidayListSerializer,
HolidayUpdateSerializer,
MarkWeekendsSerializer,
SchoolClassCreateSerializer,
SchoolClassDetailSerializer,
SchoolClassListSerializer,
SchoolClassUpdateSerializer,
SectionCreateSerializer,
SectionDetailSerializer,
SectionListSerializer,
SectionUpdateSerializer,
WorkingDayCreateSerializer,
WorkingDayDetailSerializer,
WorkingDayListSerializer,
WorkingDayUpdateSerializer,
)
from .services import (
activate_academic_year,
create_academic_year,
create_class_section,
create_holiday,
create_school_class,
create_section,
create_working_day,
DEFAULT_WEEKEND_WEEKDAYS,
delete_holiday,
delete_working_day,
mark_weekends,
update_academic_year,
update_class_section,
update_holiday,
update_school_class,
update_section,
update_working_day,
)

class AcademicPaginationMixin:
    """Shared pagination and response handling for academic APIs."""


    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(
            self.get_queryset()
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)

            return paginated_response(
                message=self.list_message,
                results=serializer.data,
                count=self.paginator.page.paginator.count,
                next_url=self.paginator.get_next_link(),
                previous_url=self.paginator.get_previous_link(),
            )

        serializer = self.get_serializer(
            queryset,
            many=True,
        )

        return success_response(
            self.list_message,
            serializer.data,
        )


class AcademicCreateMixin:
    """
    Return single-object creates in the standard envelope.

    Views set ``self.instance`` in ``perform_create`` and declare
    ``detail_serializer_class`` and ``create_message``.
    """

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return created_response(
            self.create_message,
            self.detail_serializer_class(self.instance).data,
        )


class AcademicBaseMixin:
    """Shared helpers for school-scoped academic views."""

    def is_super_admin(self) -> bool:
        return IsSuperAdmin().has_permission(
            self.request,
            self,
        )

    def get_user_school(self):
        """Return the school managed by the authenticated School Admin."""

        try:
            return self.request.user.managed_school
        except AttributeError:
            raise ValidationError(
                {
                    "detail": (
                        "The authenticated user is not assigned "
                        "as an administrator of any school."
                    )
                }
            )

    def ensure_school_access(self, school) -> None:
        """Ensure the authenticated user can access the requested school."""

        if self.is_super_admin():
            return

        user_school = self.get_user_school()

        if school.id != user_school.id:
            raise ValidationError(
                {
                    "detail": (
                        "You do not have permission to access "
                        "this school's academic data."
                    )
                }
            )


class AcademicYearListCreateAPIView(
AcademicCreateMixin,
AcademicPaginationMixin,
AcademicBaseMixin,
generics.ListCreateAPIView,
):
    """List and create academic years."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_class = AcademicYearFilter
    search_fields = [
        "name",
    ]
    ordering_fields = [
        "name",
        "start_date",
        "end_date",
        "created_at",
    ]
    ordering = [
        "-start_date",
    ]
    list_message = "Academic years fetched successfully."
    create_message = "Academic year created successfully."
    detail_serializer_class = AcademicYearDetailSerializer

    def get_queryset(self) -> QuerySet:
        if self.is_super_admin():
            return get_academic_year_queryset()

        return get_academic_year_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AcademicYearCreateSerializer

        return AcademicYearListSerializer

    def perform_create(self, serializer):
        if self.is_super_admin():
            school = serializer.validated_data.get("school")
        else:
            school = self.get_user_school()

        if school is None:
            raise ValidationError(
                {
                    "school": (
                        "School is required when creating an academic "
                        "year as a Super Admin."
                    )
                }
            )

        validated_data = serializer.validated_data.copy()
        validated_data.pop("school", None)

        self.instance = create_academic_year(
            school=school,
            validated_data=validated_data,
        )


class AcademicYearDetailAPIView(
AcademicBaseMixin,
generics.RetrieveUpdateDestroyAPIView,
):
    """Retrieve, update, and delete an academic year."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]

    def get_queryset(self):
        if self.is_super_admin():
            return get_academic_year_queryset()

        return get_academic_year_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return AcademicYearUpdateSerializer

        return AcademicYearDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(instance)

        return success_response(
            "Academic year fetched successfully.",
            serializer.data,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        try:
            instance = update_academic_year(
                academic_year=instance,
                validated_data=serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)

        serializer = AcademicYearDetailSerializer(instance)

        return updated_response(
            "Academic year updated successfully.",
            serializer.data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            instance.delete()
        except IntegrityError:
            return error_response(
                "Academic year cannot be deleted because it is "
                "referenced by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response(
            "Academic year deleted successfully.",
        )


class AcademicYearActivateAPIView(
AcademicBaseMixin,
generics.GenericAPIView,
):
    """
    Activate an academic year.

    The currently active academic year for the school is automatically
    deactivated.
    """

    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]

    def get_queryset(self):
        if self.is_super_admin():
            return get_academic_year_queryset()

        return get_academic_year_queryset(
            self.get_user_school()
        )

    def post(self, request, pk):
        academic_year = self.get_object()

        try:
            academic_year = activate_academic_year(
                academic_year=academic_year,
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)

        serializer = AcademicYearDetailSerializer(
            academic_year,
        )

        return success_response(
            "Academic year activated successfully.",
            serializer.data,
        )


class SchoolClassListCreateAPIView(
    AcademicPaginationMixin,
    AcademicBaseMixin,
    generics.ListCreateAPIView,
):
    """List school classes and create multiple classes."""

    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_class = SchoolClassFilter
    search_fields = [
        "name",
    ]
    ordering_fields = [
        "name",
        "created_at",
    ]
    ordering = [
        "id",
        "-name",
    ]
    list_message = "Classes fetched successfully."

    def get_queryset(self):
        if self.is_super_admin():
            return get_school_class_queryset()

        return get_school_class_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SchoolClassCreateSerializer

        return SchoolClassListSerializer

    def create(self, request, *args, **kwargs):
        if not isinstance(request.data, list):
            raise ValidationError(
                {
                    "detail": "Expected a list of classes.",
                }
            )

        if not request.data:
            raise ValidationError(
                {
                    "detail": "At least one class is required.",
                }
            )

        is_super_admin = self.is_super_admin()

        user_school = (
            None
            if is_super_admin
            else self.get_user_school()
        )

        created = []
        failed = []

        for class_data in request.data:
            serializer = self.get_serializer(
                data=class_data,
            )

            if not serializer.is_valid():
                failed.append(
                    {
                        "name": class_data.get("name"),
                        "errors": serializer.errors,
                    }
                )
                continue

            validated_data = serializer.validated_data.copy()

            if is_super_admin:
                school = validated_data.pop(
                    "school",
                    None,
                )
            else:
                school = user_school
                validated_data.pop("school", None)

            if school is None:
                failed.append(
                    {
                        "name": class_data.get("name"),
                        "error": "School is required.",
                    }
                )
                continue

            try:
                with transaction.atomic():
                    school_class = create_school_class(
                        school=school,
                        validated_data=validated_data,
                    )

            except DjangoValidationError:
                failed.append(
                    {
                        "name": class_data.get("name"),
                        "error": (
                            "A class with this name already exists."
                        ),
                    }
                )
                continue

            except IntegrityError:
                failed.append(
                    {
                        "name": class_data.get("name"),
                        "error": (
                            "A class with this name already exists."
                        ),
                    }
                )
                continue

            created.append(
                {
                    "id": school_class.id,
                    "name": school_class.name,
                }
            )

        return Response(
            {
                "success": True,
                "message": "Classes processed successfully.",
                "data": {
                    "created": created,
                    "failed": failed,
                },
            },
            status=status.HTTP_200_OK,
        )


class SchoolClassDetailAPIView(
AcademicBaseMixin,
generics.RetrieveUpdateDestroyAPIView,
):
    """Retrieve, update, and delete a school class."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]

    def get_queryset(self):
        if self.is_super_admin():
            return get_school_class_queryset()

        return get_school_class_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return SchoolClassUpdateSerializer

        return SchoolClassDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(instance)

        return success_response(
            "Class fetched successfully.",
            serializer.data,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        try:
            school = (
                None
                if self.is_super_admin()
                else self.get_user_school()
            )
            instance = update_school_class(
                school_class=instance,
                validated_data=serializer.validated_data,
                school=school,
            )
        except IntegrityError:
            raise ValidationError(
                {
                    "name": (
                        "A class with this name already exists "
                        "for this school."
                    )
                }
            )

        serializer = SchoolClassDetailSerializer(instance)

        return updated_response(
            "Class updated successfully.",
            serializer.data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            instance.delete()
        except IntegrityError:
            return error_response(
                "Class cannot be deleted because it is referenced "
                "by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response(
            "Class deleted successfully.",
        )


class SectionListCreateAPIView(
    AcademicPaginationMixin,
    AcademicBaseMixin,
    generics.ListCreateAPIView,
):
    """List sections and create multiple sections."""

    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_class = SectionFilter
    search_fields = [
        "name",
    ]
    ordering_fields = [
        "name",
        "created_at",
    ]
    ordering = [
        "name",
    ]
    list_message = "Sections fetched successfully."

    def get_queryset(self):
        if self.is_super_admin():
            return get_section_queryset()

        return get_section_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SectionCreateSerializer

        return SectionListSerializer

    def create(self, request, *args, **kwargs):
        if not isinstance(request.data, list):
            raise ValidationError(
                {
                    "detail": "Expected a list of sections.",
                }
            )

        if not request.data:
            raise ValidationError(
                {
                    "detail": "At least one section is required.",
                }
            )

        is_super_admin = self.is_super_admin()

        user_school = (
            None
            if is_super_admin
            else self.get_user_school()
        )

        created = []
        failed = []

        for section_data in request.data:
            serializer = self.get_serializer(
                data=section_data,
            )

            if not serializer.is_valid():
                failed.append(
                    {
                        "name": section_data.get("name"),
                        "errors": serializer.errors,
                    }
                )
                continue

            validated_data = serializer.validated_data.copy()

            if is_super_admin:
                school = validated_data.pop(
                    "school",
                    None,
                )
            else:
                school = user_school
                validated_data.pop("school", None)

            if school is None:
                failed.append(
                    {
                        "name": section_data.get("name"),
                        "error": "School is required.",
                    }
                )
                continue

            try:
                with transaction.atomic():
                    section = create_section(
                        school=school,
                        validated_data=validated_data,
                    )

            except DjangoValidationError:
                failed.append(
                    {
                        "name": section_data.get("name"),
                        "error": (
                            "A section with this name already exists."
                        ),
                    }
                )
                continue

            except IntegrityError:
                failed.append(
                    {
                        "name": section_data.get("name"),
                        "error": (
                            "A section with this name already exists."
                        ),
                    }
                )
                continue

            created.append(
                {
                    "id": section.id,
                    "name": section.name,
                }
            )

        return Response(
            {
                "success": True,
                "message": "Sections processed successfully.",
                "data": {
                    "created": created,
                    "failed": failed,
                },
            },
            status=status.HTTP_200_OK,
        )


class SectionDetailAPIView(
AcademicBaseMixin,
generics.RetrieveUpdateDestroyAPIView,
):
    """Retrieve, update, and delete a section."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]

    def get_queryset(self):
        if self.is_super_admin():
            return get_section_queryset()

        return get_section_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return SectionUpdateSerializer

        return SectionDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(instance)

        return success_response(
            "Section fetched successfully.",
            serializer.data,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        try:
            instance = update_section(
                section=instance,
                validated_data=serializer.validated_data,
            )
        except IntegrityError:
            raise ValidationError(
                {
                    "name": (
                        "A section with this name already exists "
                        "for this school."
                    )
                }
            )

        serializer = SectionDetailSerializer(instance)

        return updated_response(
            "Section updated successfully.",
            serializer.data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            instance.delete()
        except IntegrityError:
            return error_response(
                "Section cannot be deleted because it is referenced "
                "by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response(
            "Section deleted successfully.",
        )


class ClassSectionListCreateAPIView(
    AcademicPaginationMixin,
    AcademicBaseMixin,
    generics.ListCreateAPIView,
):
    """List class-section combinations and create multiple combinations."""

    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]
    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]
    filterset_class = ClassSectionFilter
    ordering_fields = [
        "academic_year__start_date",
        "school_class__name",
        "section__name",
        "created_at",
    ]
    ordering = [
        "academic_year__start_date",
        "school_class__name",
        "section__name",
    ]
    list_message = "Class sections fetched successfully."

    def get_queryset(self):
        if self.is_super_admin():
            return get_class_section_queryset()

        return get_class_section_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ClassSectionCreateSerializer

        return ClassSectionListSerializer

    def create(self, request, *args, **kwargs):
        if not isinstance(request.data, list):
            raise ValidationError(
                {
                    "detail": (
                        "Expected a list of class-section "
                        "combinations."
                    ),
                }
            )

        if not request.data:
            raise ValidationError(
                {
                    "detail": (
                        "At least one class-section combination "
                        "is required."
                    ),
                }
            )

        is_super_admin = self.is_super_admin()

        user_school = (
            None
            if is_super_admin
            else self.get_user_school()
        )

        created = []
        failed = []

        for item in request.data:
            serializer = self.get_serializer(
                data=item,
            )

            if not serializer.is_valid():
                failed.append(
                    {
                        "academic_year": item.get(
                            "academic_year"
                        ),
                        "school_class": item.get(
                            "school_class"
                        ),
                        "section": item.get("section"),
                        "errors": serializer.errors,
                    }
                )
                continue

            validated_data = (
                serializer.validated_data.copy()
            )

            academic_year = validated_data[
                "academic_year"
            ]
            school_class = validated_data[
                "school_class"
            ]
            section = validated_data["section"]

            school = academic_year.school

            if (
                not is_super_admin
                and school.id != user_school.id
            ):
                failed.append(
                    {
                        "academic_year": academic_year.id,
                        "school_class": school_class.id,
                        "section": section.id,
                        "error": (
                            "You do not have permission to "
                            "access this academic year."
                        ),
                    }
                )
                continue

            if school_class.school_id != school.id:
                failed.append(
                    {
                        "academic_year": academic_year.id,
                        "school_class": school_class.id,
                        "section": section.id,
                        "error": (
                            "The selected class does not belong "
                            "to the academic year's school."
                        ),
                    }
                )
                continue

            if section.school_id != school.id:
                failed.append(
                    {
                        "academic_year": academic_year.id,
                        "school_class": school_class.id,
                        "section": section.id,
                        "error": (
                            "The selected section does not belong "
                            "to the academic year's school."
                        ),
                    }
                )
                continue

            try:
                with transaction.atomic():
                    class_section = create_class_section(
                        school=school,
                        validated_data=validated_data,
                    )

            except DjangoValidationError:
                failed.append(
                    {
                        "academic_year": academic_year.id,
                        "school_class": school_class.id,
                        "section": section.id,
                        "error": (
                            "This class-section combination is "
                            "invalid or already exists."
                        ),
                    }
                )
                continue

            except IntegrityError:
                failed.append(
                    {
                        "academic_year": academic_year.id,
                        "school_class": school_class.id,
                        "section": section.id,
                        "error": (
                            "This class-section combination "
                            "already exists."
                        ),
                    }
                )
                continue

            created.append(
                {
                    "id": class_section.id,
                    "academic_year": {
                        "id": academic_year.id,
                        "name": academic_year.name,
                    },
                    "school_class": {
                        "id": school_class.id,
                        "name": school_class.name,
                    },
                    "section": {
                        "id": section.id,
                        "name": section.name,
                    },
                }
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Class-section combinations processed "
                    "successfully."
                ),
                "data": {
                    "created": created,
                    "failed": failed,
                },
            },
            status=status.HTTP_200_OK,
        )


class ClassSectionDetailAPIView(
AcademicBaseMixin,
generics.RetrieveUpdateDestroyAPIView,
):
    """Retrieve, update, and delete a class-section combination."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]

    def get_queryset(self):
        if self.is_super_admin():
            return get_class_section_queryset()

        return get_class_section_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return ClassSectionUpdateSerializer

        return ClassSectionDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(instance)

        return success_response(
            "Class section fetched successfully.",
            serializer.data,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        try:
            instance = update_class_section(
                class_section=instance,
                validated_data=serializer.validated_data,
                school=(
                    None
                    if self.is_super_admin()
                    else self.get_user_school()
                ),
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)
        except IntegrityError:
            raise ValidationError(
                {
                    "non_field_errors": (
                        "This class-section combination already "
                        "exists for this academic year."
                    )
                }
            )
        serializer = ClassSectionDetailSerializer(instance)

        return updated_response(
            "Class section updated successfully.",
            serializer.data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            instance.delete()
        except IntegrityError:
            return error_response(
                "Class section cannot be deleted because it is "
                "referenced by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response(
            "Class section deleted successfully.",
        )


class HolidayListCreateAPIView(
AcademicCreateMixin,
AcademicPaginationMixin,
AcademicBaseMixin,
generics.ListCreateAPIView,
):
    """List and create holidays."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_class = HolidayFilter
    search_fields = [
        "title",
        "description",
    ]
    ordering_fields = [
        "date",
        "title",
        "created_at",
    ]
    ordering = [
        "date",
    ]
    list_message = "Holidays fetched successfully."
    create_message = "Holiday created successfully."
    detail_serializer_class = HolidayDetailSerializer

    def get_queryset(self):
        if self.is_super_admin():
            return get_holiday_queryset()

        return get_holiday_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return HolidayCreateSerializer

        return HolidayListSerializer

    def perform_create(self, serializer):
        academic_year = serializer.validated_data["academic_year"]

        if not self.is_super_admin():
            self.ensure_school_access(
                academic_year.school,
            )

        try:
            self.instance = create_holiday(
                school=academic_year.school,
                validated_data=serializer.validated_data,
            )
        except IntegrityError:
            raise ValidationError(
                {
                    "date": (
                        "A holiday already exists for this date "
                        "and school."
                    )
                }
            )


class HolidayDetailAPIView(
AcademicBaseMixin,
generics.RetrieveUpdateDestroyAPIView,
):
    """Retrieve, update, and delete a holiday."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]

    def get_queryset(self):
        if self.is_super_admin():
            return get_holiday_queryset()

        return get_holiday_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return HolidayUpdateSerializer

        return HolidayDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(instance)

        return success_response(
            "Holiday fetched successfully.",
            serializer.data,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        try:
            instance = update_holiday(
                holiday=instance,
                validated_data=serializer.validated_data,
            )
        except IntegrityError:
            raise ValidationError(
                {
                    "date": (
                        "A holiday already exists for this date "
                        "and school."
                    )
                }
            )

        serializer = HolidayDetailSerializer(instance)

        return updated_response(
            "Holiday updated successfully.",
            serializer.data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            delete_holiday(holiday=instance)
        except IntegrityError:
            return error_response(
                "Holiday cannot be deleted because it is referenced "
                "by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response(
            "Holiday deleted successfully.",
        )


class WorkingDayListCreateAPIView(
AcademicCreateMixin,
AcademicPaginationMixin,
AcademicBaseMixin,
generics.ListCreateAPIView,
):
    """List and create working-day records."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]
    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]
    filterset_class = WorkingDayFilter
    ordering_fields = [
        "date",
        "day_type",
        "created_at",
    ]
    ordering = [
        "date",
    ]
    list_message = "Working days fetched successfully."
    create_message = "Working day created successfully."
    detail_serializer_class = WorkingDayDetailSerializer

    def get_queryset(self):
        if self.is_super_admin():
            return get_working_day_queryset()

        return get_working_day_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return WorkingDayCreateSerializer

        return WorkingDayListSerializer

    def perform_create(self, serializer):
        academic_year = serializer.validated_data["academic_year"]

        if not self.is_super_admin():
            self.ensure_school_access(
                academic_year.school,
            )

        try:
            self.instance = create_working_day(
                school=academic_year.school,
                validated_data=serializer.validated_data,
            )
        except IntegrityError:
            raise ValidationError(
                {
                    "date": (
                        "A working-day record already exists "
                        "for this date and school."
                    )
                }
            )


class WorkingDayDetailAPIView(
AcademicBaseMixin,
generics.RetrieveUpdateDestroyAPIView,
):
    """Retrieve, update, and delete working-day records."""


    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]

    def get_queryset(self):
        if self.is_super_admin():
            return get_working_day_queryset()

        return get_working_day_queryset(
            self.get_user_school()
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return WorkingDayUpdateSerializer

        return WorkingDayDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(instance)

        return success_response(
            "Working day fetched successfully.",
            serializer.data,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        try:
            instance = update_working_day(
                working_day=instance,
                validated_data=serializer.validated_data,
            )
        except IntegrityError:
            raise ValidationError(
                {
                    "date": (
                        "A working-day record already exists "
                        "for this date and school."
                    )
                }
            )

        serializer = WorkingDayDetailSerializer(instance)

        return updated_response(
            "Working day updated successfully.",
            serializer.data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            delete_working_day(working_day=instance)
        except IntegrityError:
            return error_response(
                "Working day cannot be deleted because it is referenced "
                "by other records.",
                status_code=status.HTTP_409_CONFLICT,
            )

        return deleted_response(
            "Working day deleted successfully.",
        )


class WorkingDayMarkWeekendsAPIView(
AcademicBaseMixin,
generics.GenericAPIView,
):
    """
    Mark recurring weekdays as weekends across an academic year.

    Defaults to every Sunday in the academic year. Existing working-day
    records are kept unless ``overwrite`` is set.
    """

    permission_classes = [
        IsAuthenticated,
        IsAcademicAdmin,
    ]
    serializer_class = MarkWeekendsSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        academic_year = validated_data["academic_year"]

        self.ensure_school_access(academic_year.school)

        weekdays = validated_data.get(
            "weekdays",
            DEFAULT_WEEKEND_WEEKDAYS,
        )

        try:
            summary = mark_weekends(
                school=academic_year.school,
                academic_year=academic_year,
                weekdays=weekdays,
                start_date=validated_data.get("start_date"),
                end_date=validated_data.get("end_date"),
                overwrite=validated_data["overwrite"],
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)
        except IntegrityError:
            raise ValidationError(
                {
                    "detail": (
                        "Working-day records for these dates changed "
                        "while the request was running. Please retry."
                    )
                }
            )

        return success_response(
            "Weekends marked successfully.",
            {
                "academic_year": academic_year.id,
                "weekdays": [int(weekday) for weekday in weekdays],
                **summary,
            },
        )
