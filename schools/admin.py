from django.contrib import admin

from .models import School


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "email",
        "phone",
        "admin",
        "status",
        "city",
        "state",
        "created_at",
    )

    list_filter = (
        "status",
        "state",
        "city",
        "created_at",
    )

    search_fields = (
        "name",
        "code",
        "email",
        "phone",
        "admin__name",
        "admin__email",
    )

    ordering = ("-created_at",)

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "School Information",
            {
                "fields": (
                    "name",
                    "code",
                    "email",
                    "phone",
                    "status",
                    "logo",
                )
            },
        ),
        (
            "Address",
            {
                "fields": (
                    "address",
                    "city",
                    "state",
                    "country",
                    "pincode",
                )
            },
        ),
        (
            "Relationships",
            {
                "fields": (
                    "admin",
                )
            },
        ),
        (
            "System",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )