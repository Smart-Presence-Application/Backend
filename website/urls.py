from django.urls import path

from . import views

app_name = "website"

urlpatterns = [
    path("testimonials/", views.PublicTestimonialListAPIView.as_view(), name="testimonials"),
    path("partners/", views.PublicPartnerListAPIView.as_view(), name="partners"),
    path("contact/", views.ContactSubmitAPIView.as_view(), name="contact"),
    path("admin/testimonials/", views.TestimonialListCreateAPIView.as_view(), name="admin-testimonials"),
    path("admin/testimonials/<int:pk>/", views.TestimonialDetailAPIView.as_view(), name="admin-testimonial"),
    path("admin/partners/", views.PartnerListCreateAPIView.as_view(), name="admin-partners"),
    path("admin/partners/<int:pk>/", views.PartnerDetailAPIView.as_view(), name="admin-partner"),
    path("admin/messages/", views.ContactMessageListAPIView.as_view(), name="admin-messages"),
    path("admin/messages/<int:pk>/", views.ContactMessageDetailAPIView.as_view(), name="admin-message"),
]
