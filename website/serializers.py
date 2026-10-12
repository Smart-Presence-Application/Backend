from rest_framework import serializers

from .models import ContactMessage, Partner, Testimonial


class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = [
            "id",
            "name",
            "role",
            "organization",
            "quote",
            "rating",
            "photo",
            "is_published",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PublicTestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = ["id", "name", "role", "organization", "quote", "rating", "photo"]


class PartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = ["id", "name", "logo", "website", "is_published", "sort_order", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class PublicPartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = ["id", "name", "logo", "website"]


class ContactSubmitSerializer(serializers.Serializer):
    """
    ``turnstile_token`` is Cloudflare Turnstile's token from the widget.
    ``website`` is a honeypot people never see; bots that fill every
    input give themselves away.
    """

    name = serializers.CharField(max_length=120, trim_whitespace=True)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    school = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    message = serializers.CharField(max_length=3000, min_length=10, trim_whitespace=True)
    turnstile_token = serializers.CharField(required=False, allow_blank=True, default="")
    website = serializers.CharField(required=False, allow_blank=True, default="")


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["id", "name", "email", "phone", "school", "message", "email_sent", "is_read", "ip_address", "created_at"]
        read_only_fields = [f for f in fields if f != "is_read"]
