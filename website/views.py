"""Public website content and the contact form, plus Super Admin management of both."""

import logging

from rest_framework import filters, generics
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from common.pagination import StandardResultsPagination
from common.permissions import IsSuperAdmin
from common.responses import created_response, deleted_response, success_response, updated_response
from common.throttling import ContactRateThrottle, client_ip

from . import services
from .models import ContactMessage, Partner, Testimonial
from .serializers import (
    ContactMessageSerializer,
    ContactSubmitSerializer,
    PartnerSerializer,
    PublicPartnerSerializer,
    PublicTestimonialSerializer,
    TestimonialSerializer,
)

logger = logging.getLogger(__name__)


class PublicListMixin:
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None

    def list(self, request, *args, **kwargs):
        return success_response("Fetched successfully.", self.get_serializer(self.get_queryset(), many=True).data)


class PublicTestimonialListAPIView(PublicListMixin, generics.ListAPIView):
    """Published testimonials for the home page; empty hides the section."""

    serializer_class = PublicTestimonialSerializer
    queryset = Testimonial.objects.filter(is_published=True)


class PublicPartnerListAPIView(PublicListMixin, generics.ListAPIView):
    """Published partner logos for the home page."""

    serializer_class = PublicPartnerSerializer
    queryset = Partner.objects.filter(is_published=True)


class ContactSubmitAPIView(generics.GenericAPIView):
    """
    The website's contact form. Protected by Cloudflare Turnstile, a hidden
    honeypot field and a per-address rate limit; the enquiry is stored and
    emailed to CONTACT_RECIPIENT_EMAIL. A filled honeypot still gets a
    success answer, so bots do not learn what tripped them.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ContactRateThrottle]
    serializer_class = ContactSubmitSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data["website"]:
            logger.info("Contact form honeypot filled from %s; ignored.", client_ip(request))
            return created_response("Thank you! We will get back to you soon.")

        if not services.verify_turnstile(data["turnstile_token"], client_ip(request)):
            raise ValidationError({"turnstile_token": "Please complete the spam check and try again."})

        services.submit_contact(data=data, request=request)

        return created_response("Thank you! We will get back to you soon.")


class SuperAdminMixin:
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class EnvelopeListCreateView(SuperAdminMixin, generics.ListCreateAPIView):
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter]
    noun = "Item"

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return created_response(f"{self.noun} added.", serializer.data)


class EnvelopeDetailView(SuperAdminMixin, generics.RetrieveUpdateDestroyAPIView):
    noun = "Item"

    def retrieve(self, request, *args, **kwargs):
        return success_response(f"{self.noun} fetched.", self.get_serializer(self.get_object()).data)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return updated_response(f"{self.noun} updated.", serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Delete the row along with its stored image."""

        instance = self.get_object()
        for field in ("photo", "logo"):
            image = getattr(instance, field, None)
            if image:
                image.delete(save=False)
        instance.delete()
        return deleted_response(f"{self.noun} deleted.")


class TestimonialListCreateAPIView(EnvelopeListCreateView):
    serializer_class = TestimonialSerializer
    queryset = Testimonial.objects.all()
    search_fields = ["name", "organization", "quote"]
    noun = "Testimonial"


class TestimonialDetailAPIView(EnvelopeDetailView):
    serializer_class = TestimonialSerializer
    queryset = Testimonial.objects.all()
    noun = "Testimonial"


class PartnerListCreateAPIView(EnvelopeListCreateView):
    serializer_class = PartnerSerializer
    queryset = Partner.objects.all()
    search_fields = ["name", "website"]
    noun = "Partner"


class PartnerDetailAPIView(EnvelopeDetailView):
    serializer_class = PartnerSerializer
    queryset = Partner.objects.all()
    noun = "Partner"


class ContactMessageListAPIView(SuperAdminMixin, generics.ListAPIView):
    """Enquiries from the contact form, newest first. ``?is_read=false`` for new ones."""

    serializer_class = ContactMessageSerializer
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "email", "school", "message"]

    def get_queryset(self):
        queryset = ContactMessage.objects.all()
        is_read = self.request.query_params.get("is_read")

        if is_read in ("true", "false"):
            queryset = queryset.filter(is_read=is_read == "true")

        return queryset


class ContactMessageDetailAPIView(SuperAdminMixin, generics.GenericAPIView):
    """Mark an enquiry read or unread, or delete it."""

    serializer_class = ContactMessageSerializer
    queryset = ContactMessage.objects.all()

    def patch(self, request, pk, *args, **kwargs):
        message = self.get_object()
        message.is_read = bool(request.data.get("is_read", True))
        message.save(update_fields=["is_read"])
        return updated_response("Enquiry updated.", self.get_serializer(message).data)

    def delete(self, request, pk, *args, **kwargs):
        self.get_object().delete()
        return deleted_response("Enquiry deleted.")
