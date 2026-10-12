from rest_framework import serializers

from accounts.models import User
from accounts.serializers import UserSerializer
from common.choices import Status
from .models import School
from .validators import (
    validate_unique_school_code,
    validate_unique_school_email,
)

class SchoolStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=Status.choices,
    )


class SchoolSerializer(serializers.ModelSerializer):
    """Serializer for school data."""

    class Meta:
        model = School
        fields = (
            "id",
            "name",
            "code",
            "email",
            "phone",
            "address",
            "city",
            "state",
            "country",
            "pincode",
            "logo",
            "status",
            "attendance_threshold",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "status",
            "created_at",
            "updated_at",
        )


class SchoolAdminCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a school admin.

    Email and phone are optional on User (parents have no email), but a
    school admin needs both to sign in and be contacted.
    """

    class Meta:
        model = User
        fields = (
            "name",
            "email",
            "phone_number",
        )
        extra_kwargs = {
            "email": {"required": True, "allow_null": False, "allow_blank": False},
            "phone_number": {"required": True, "allow_blank": False},
        }


class SchoolCreateSerializer(serializers.Serializer):
    """Serializer for creating a school and its admin."""

    school = SchoolSerializer()
    admin = SchoolAdminCreateSerializer()

    def validate(self, attrs):
        school = attrs["school"]

        validate_unique_school_code(school["code"])
        validate_unique_school_email(school["email"])

        return attrs


class SchoolUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating school information."""

    class Meta:
        model = School
        fields = (
            "name",
            "email",
            "phone",
            "address",
            "city",
            "state",
            "country",
            "pincode",
            "logo",
            "attendance_threshold",
        )


class SchoolListSerializer(serializers.ModelSerializer):
    """Serializer for listing schools."""

    admin_name = serializers.CharField(
        source="admin.name",
        read_only=True,
    )

    class Meta:
        model = School
        fields = (
            "id",
            "name",
            "code",
            "email",
            "phone",
            "city",
            "state",
            "status",
            "admin_name",
            "attendance_threshold",
        )


class SchoolDetailSerializer(serializers.ModelSerializer):
    """Serializer for school details."""

    admin = UserSerializer(read_only=True)

    class Meta:
        model = School
        fields = (
            "id",
            "name",
            "code",
            "email",
            "phone",
            "address",
            "city",
            "state",
            "country",
            "pincode",
            "logo",
            "status",
            "admin",
            "attendance_threshold",
            "created_at",
            "updated_at",
        )
        

class SchoolLogoSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ("logo",)