from django.urls import path

from .views import (
    AcademicYearActivateAPIView,
    AcademicYearDetailAPIView,
    AcademicYearListCreateAPIView,
    ClassSectionDetailAPIView,
    ClassSectionListCreateAPIView,
    HolidayDetailAPIView,
    HolidayListCreateAPIView,
    SchoolClassDetailAPIView,
    SchoolClassListCreateAPIView,
    SectionDetailAPIView,
    SectionListCreateAPIView,
    WorkingDayDetailAPIView,
    WorkingDayListCreateAPIView,
    WorkingDayMarkWeekendsAPIView,
)

from .calendar_views import SchoolCalendarAPIView

app_name = "academics"

urlpatterns = [
    path(
        "calendar/",
        SchoolCalendarAPIView.as_view(),
        name="calendar",
    ),

    path(
        "years/",
        AcademicYearListCreateAPIView.as_view(),
        name="academic-year-list-create",
    ),
    path(
        "years/<int:pk>/",
        AcademicYearDetailAPIView.as_view(),
        name="academic-year-detail",
    ),
    path(
        "years/<int:pk>/activate/",
        AcademicYearActivateAPIView.as_view(),
        name="academic-year-activate",
    ),

    path(
        "classes/",
        SchoolClassListCreateAPIView.as_view(),
        name="class-list-create",
    ),
    path(
        "classes/<int:pk>/",
        SchoolClassDetailAPIView.as_view(),
        name="class-detail",
    ),

    path(
        "sections/",
        SectionListCreateAPIView.as_view(),
        name="section-list-create",
    ),
    path(
        "sections/<int:pk>/",
        SectionDetailAPIView.as_view(),
        name="section-detail",
    ),

    path(
        "class-sections/",
        ClassSectionListCreateAPIView.as_view(),
        name="class-section-list-create",
    ),
    path(
        "class-sections/<int:pk>/",
        ClassSectionDetailAPIView.as_view(),
        name="class-section-detail",
    ),

    path(
        "holidays/",
        HolidayListCreateAPIView.as_view(),
        name="holiday-list-create",
    ),
    path(
        "holidays/<int:pk>/",
        HolidayDetailAPIView.as_view(),
        name="holiday-detail",
    ),

    path(
        "working-days/",
        WorkingDayListCreateAPIView.as_view(),
        name="working-day-list-create",
    ),
    path(
        "working-days/mark-weekends/",
        WorkingDayMarkWeekendsAPIView.as_view(),
        name="working-day-mark-weekends",
    ),
    path(
        "working-days/<int:pk>/",
        WorkingDayDetailAPIView.as_view(),
        name="working-day-detail",
    ),
]