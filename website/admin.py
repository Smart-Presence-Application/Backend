from django.contrib import admin

from .models import ContactMessage, Partner, Testimonial


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_published", "sort_order")
    list_filter = ("is_published",)


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "is_published", "sort_order")
    list_filter = ("is_published",)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "school", "email_sent", "is_read", "created_at")
    list_filter = ("is_read", "email_sent")
    search_fields = ("name", "email", "school", "message")
