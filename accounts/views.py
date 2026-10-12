"""Authentication API views."""
from django.conf import settings
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.parsers import MultiPartParser, FormParser
from accounts.authentication import delete_token_cookie, set_token_cookie
from common.throttling import LOGIN_THROTTLES
from accounts.serializers import (
    BulkUserStatusSerializer,
    ChangePasswordSerializer,
    EmptySerializer,
    LoginSerializer,
    SingleUserStatusSerializer,
    UserSerializer,
    UserUpdateSerializer,
    ProfileImageSerializer,
)
from accounts.selectors import (
    get_user_by_id,
    get_users,
    get_users_by_ids,
)
from accounts.services import (
    change_user_password,
    login_user,
    logout_user,
    refresh_user_tokens,
    set_user_status,
    update_user_details,
    update_user_profile_image,
)
from accounts.user_filters import UserFilter
from common.permissions import IsUserAdmin
from common.responses import (
    error_response,
    success_response,
    updated_response,
    not_found_response,
)


class LoginView(GenericAPIView):
    """Email login; throttled per address and per account to limit password guessing."""

    serializer_class = LoginSerializer
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

        result = login_user(serializer.validated_data["user"])

        response = success_response(
            "Login successful.",
            {"user": UserSerializer(result["user"]).data},
            status.HTTP_200_OK,
        )

        set_token_cookie(
            response,
            settings.JWT_ACCESS_COOKIE,
            result["tokens"]["access"],
        )
        set_token_cookie(
            response,
            settings.JWT_REFRESH_COOKIE,
            result["tokens"]["refresh"],
        )

        return response


class LogoutView(GenericAPIView):
    serializer_class = EmptySerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        logout_user(request.COOKIES.get(settings.JWT_REFRESH_COOKIE))

        response = success_response(
            "Logout successful.",
            None,
            status.HTTP_200_OK,
        )

        delete_token_cookie(response, settings.JWT_ACCESS_COOKIE)
        delete_token_cookie(response, settings.JWT_REFRESH_COOKIE)

        return response


class RefreshView(GenericAPIView):
    serializer_class = EmptySerializer
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request, *args, **kwargs):
        try:
            tokens = refresh_user_tokens(
                request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
            )
        except TokenError as exc:
            return error_response(
                str(exc),
                None,
                status.HTTP_401_UNAUTHORIZED,
            )

        response = success_response(
            "Token refreshed successfully.",
            None,
            status.HTTP_200_OK,
        )

        set_token_cookie(response, settings.JWT_ACCESS_COOKIE, tokens["access"])
        set_token_cookie(response, settings.JWT_REFRESH_COOKIE, tokens["refresh"])

        return response


class ProfileView(GenericAPIView):
    permission_classes = (IsAuthenticated,)

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return UserUpdateSerializer
        return UserSerializer


    def get(self, request, *args, **kwargs):
        return success_response(
            "Profile fetched successfully.",
            {"user": self.get_serializer(request.user).data},
        )
        
    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=True)
        
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        user = update_user_details(
            user=request.user,
            validated_data=serializer.validated_data,
        )

        return updated_response(
            "Profile updated successfully.",
            {"user": UserSerializer(user).data},
        )


class ProfileImageView(GenericAPIView):
    serializer_class = ProfileImageSerializer
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    def patch(self, request):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        user = update_user_profile_image(
            user=request.user,
            image=serializer.validated_data["profile_image"],
        )

        return updated_response(
            "Profile image updated successfully.",
            {"user": UserSerializer(user).data},
        )


class ChangePasswordView(GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        if self.kwargs.get("user_id") is not None:
            return [IsUserAdmin()]

        return super().get_permissions()

    def get_target_user(self):
        user_id = self.kwargs.get("user_id")

        if user_id is None:
            return self.request.user

        return get_user_by_id(user_id, actor=self.request.user)

    def post(self, request, *args, **kwargs):
        target_user = self.get_target_user()
        
        if not target_user:
            return not_found_response("User not found.")

        serializer = self.get_serializer(
            data=request.data,
            context={
                "request": request,
                "target_user": target_user,
            },
        )
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        change_user_password(
            target_user,
            serializer.validated_data["new_password"],
            changed_by=request.user,
        )

        return updated_response("Password changed successfully.")


class UserView(GenericAPIView):
    permission_classes = (IsUserAdmin,)

    filter_backends = (
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    )

    filterset_class = UserFilter

    search_fields = (
        "name",
        "email",
        "phone_number",
    )

    ordering_fields = (
        "name",
        "email",
        "date_joined",
        "last_login",
    )

    ordering = ("-date_joined",)

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return UserUpdateSerializer
        return UserSerializer

    def get_queryset(self):
        return get_users(actor=self.request.user)

    def get(self, request, user_id=None, *args, **kwargs):
        if user_id:
            user = get_user_by_id(user_id, actor=request.user)

            if not user:
                return not_found_response("User not found.")

            return success_response(
                "User fetched successfully.",
                {"user": UserSerializer(user).data},
            )

        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = UserSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = UserSerializer(queryset, many=True)

        return success_response(
            "Users fetched successfully.",
            {"users": serializer.data},
        )

    def patch(self, request, user_id, *args, **kwargs):
        target_user = get_user_by_id(user_id, actor=request.user)

        if not target_user:
            return not_found_response("User not found.")

        serializer = self.get_serializer(data=request.data, partial=True)
        
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        user = update_user_details(
            user=target_user,
            validated_data=serializer.validated_data,
        )

        return updated_response(
            "User updated successfully.",
            {"user": UserSerializer(user).data},
        )
        

class SingleUserStatusView(GenericAPIView):
    serializer_class = SingleUserStatusSerializer
    permission_classes = (IsUserAdmin,)

    def patch(self, request, user_id, *args, **kwargs):
        target_user = get_user_by_id(user_id, actor=request.user)
        
        if not target_user:
            return not_found_response("User not found.")

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        changed = set_user_status(
            target_user,
            serializer.validated_data["is_active"],
            changed_by=request.user,
        )

        action = "activated" if target_user.is_active else "deactivated"

        message = (
            f"User account {action} successfully."
            if changed
            else f"User account is already {action}."
        )

        return updated_response(
            message,
            {"user": UserSerializer(target_user).data},
        )

    def post(self, request, user_id, *args, **kwargs):
        return self.patch(request, user_id, *args, **kwargs)


class BulkUserStatusView(GenericAPIView):
    serializer_class = BulkUserStatusSerializer
    permission_classes = (IsUserAdmin,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                errors=serializer.errors,
            )

        requested_ids = serializer.validated_data["user_ids"]

        users = list(get_users_by_ids(requested_ids, actor=request.user))

        skipped_ids = sorted(set(requested_ids) - {user.pk for user in users})

        changed = 0

        for user in users:
            if set_user_status(
                user,
                serializer.validated_data["is_active"],
                changed_by=request.user,
            ):
                changed += 1

        return updated_response(
            "User accounts updated successfully.",
            {
                "requested": len(set(requested_ids)),
                "matched": len(users),
                "updated": changed,
                "skipped_ids": skipped_ids,
            },
        )
