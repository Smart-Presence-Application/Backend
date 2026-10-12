from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics

from common.permissions import IsSchoolAdmin, IsSuperAdmin
from common.responses import (
    success_response,
    created_response,
    updated_response,
    deleted_response,
    not_found_response,
    error_response,
    paginated_response,
)

from .school_filters import SchoolFilter
from .selectors import (
    get_school,
    get_school_by_admin,
    list_schools,
)

from .serializers import (
    SchoolCreateSerializer,
    SchoolDetailSerializer,
    SchoolListSerializer,
    SchoolUpdateSerializer,
    SchoolStatusSerializer,
    SchoolLogoSerializer,
)

from .services import (
    create_school,
    update_school,
    delete_school,
    change_school_status,
)


class SchoolListCreateAPIView(generics.GenericAPIView):
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_class = SchoolFilter

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SchoolCreateSerializer
        return SchoolListSerializer

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(list_schools())

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)

            return paginated_response(
                message="Schools fetched successfully.",
                results=serializer.data,
                count=self.paginator.page.paginator.count,
                next_url=self.paginator.get_next_link(),
                previous_url=self.paginator.get_previous_link(),
            )

        serializer = self.get_serializer(queryset, many=True)

        return paginated_response(
            message="Schools fetched successfully.",
            results=serializer.data,
            count=queryset.count(),
            next_url=None,
            previous_url=None,
        )

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        school = create_school(
            validated_data=serializer.validated_data,
        )

        return created_response(
            message="School created successfully.",
            data=SchoolDetailSerializer(school).data,
        )


class SchoolDetailAPIView(generics.GenericAPIView):
    permission_classes = [IsSuperAdmin]

    def get_object(self):
        return get_school(self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        school = self.get_object()

        if school is None:
            return not_found_response("School not found.")

        serializer = SchoolDetailSerializer(school)

        return success_response(
            message="School fetched successfully.",
            data=serializer.data,
        )

    def patch(self, request, *args, **kwargs):
        school = self.get_object()

        if school is None:
            return not_found_response("School not found.")

        serializer = SchoolUpdateSerializer(
            school,
            data=request.data,
            partial=True,
        )
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        school = update_school(
            school=school,
            validated_data=serializer.validated_data,
        )

        return updated_response(
            message="School updated successfully.",
            data=SchoolDetailSerializer(school).data,
        )

    def delete(self, request, *args, **kwargs):
        school = self.get_object()

        if school is None:
            return not_found_response("School not found.")

        delete_school(school=school)

        return deleted_response(
            message="School deleted successfully.",
        )
        
        
class SchoolStatusAPIView(generics.GenericAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = SchoolStatusSerializer

    def patch(self, request, *args, **kwargs):
        school = get_school(self.kwargs["pk"])

        if school is None:
            return not_found_response("School not found.")

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        school = change_school_status(
            school=school,
            status=serializer.validated_data["status"],
        )

        return updated_response(
            message="School status updated successfully.",
            data=SchoolDetailSerializer(school).data,
        )


class MySchoolAPIView(generics.GenericAPIView):
    permission_classes = [IsSchoolAdmin]

    def get_object(self):
        return get_school_by_admin(self.request.user.id)

    def get(self, request, *args, **kwargs):
        school = self.get_object()

        if school is None:
            return not_found_response("School not found.")

        serializer = SchoolDetailSerializer(school)

        return success_response(
            message="School fetched successfully.",
            data=serializer.data,
        )
        
        
class MySchoolLogoAPIView(generics.GenericAPIView):
    permission_classes = [IsSchoolAdmin]
    serializer_class = SchoolLogoSerializer

    def get_object(self):
        return get_school_by_admin(self.request.user.id)

    def patch(self, request, *args, **kwargs):
        school = self.get_object()

        if school is None:
            return not_found_response("School not found.")

        serializer = self.get_serializer(
            school,
            data=request.data,
            partial=True,
        )

        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        serializer.save()

        return updated_response(
            message="School logo updated successfully.",
            data=SchoolDetailSerializer(school).data,
        )