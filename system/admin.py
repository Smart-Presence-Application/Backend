from django.contrib import admin

from .models import MaintenanceSettings


@admin.register(MaintenanceSettings)
class MaintenanceSettingsAdmin(admin.ModelAdmin):
    list_display = ("is_enabled", "message", "updated_by", "updated_at")
