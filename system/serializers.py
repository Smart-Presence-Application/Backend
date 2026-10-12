from rest_framework import serializers

from .models import ActivityLog, MaintenanceSettings


class MaintenanceSettingsSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source="updated_by.name", read_only=True, default=None)
    display_message = serializers.CharField(read_only=True)

    class Meta:
        model = MaintenanceSettings
        fields = ["is_enabled", "message", "display_message", "updated_by_name", "updated_at"]
        read_only_fields = ["display_message", "updated_by_name", "updated_at"]
        extra_kwargs = {"message": {"allow_blank": True}}


class ActivityLogSerializer(serializers.ModelSerializer):
    succeeded = serializers.BooleanField(read_only=True)

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "created_at",
            "actor",
            "actor_name",
            "actor_identifier",
            "actor_role",
            "school",
            "school_name",
            "action",
            "category",
            "method",
            "path",
            "status_code",
            "succeeded",
            "duration_ms",
            "ip_address",
            "user_agent",
        ]
        read_only_fields = fields
