"""Serializers for account APIs."""
from django.contrib.auth import authenticate, password_validation
from rest_framework import serializers

from accounts.models import User
from common.choices import UserRole
from common.validators import validate_email, validate_password_strength


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "name", "gender", "profile_image", "phone_number", "role", "updated_at", "is_active")
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(validators=[validate_email])
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        """
        Authenticate the user.

        ModelBackend returns None for inactive users too; an inactive account
        is reported only when the password is correct, so the response never
        reveals which emails exist.
        """
        request = self.context.get("request")
        user = authenticate(request=request, username=attrs["email"], password=attrs["password"])
        if user is None:
            inactive_user = User.objects.filter(email=attrs["email"], is_active=False).first()
            if inactive_user is not None and inactive_user.check_password(attrs["password"]):
                raise serializers.ValidationError("This account is inactive.")
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("This account is inactive.")
        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value: str) -> str:
        validate_password_strength(value)
        password_validation.validate_password(value, self.context.get("target_user"))
        return value

    def validate(self, attrs: dict) -> dict:
        request = self.context["request"]
        target_user = self.context["target_user"]
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "New passwords do not match."})
        changing_other_user = request.user.pk != target_user.pk
        if changing_other_user:
            is_admin = request.user.is_superuser or request.user.role in (
                UserRole.SUPER_ADMIN,
                UserRole.SCHOOL_ADMIN,
            )
            if not is_admin:
                raise serializers.ValidationError("Only admins can change another user's password.")
        elif not target_user.check_password(attrs.get("old_password", "")):
            raise serializers.ValidationError({"old_password": "Old password is incorrect."})
        return attrs


class SingleUserStatusSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()


class EmptySerializer(serializers.Serializer):
    pass


class BulkUserStatusSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    is_active = serializers.BooleanField()


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "name",
            "phone_number",
            "gender",
        )


class ProfileImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("profile_image",)
        extra_kwargs = {"profile_image": {"required": True, "allow_null": False}}