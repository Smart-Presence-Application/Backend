"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from config import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/schools/", include("schools.urls")),
    path("api/academics/", include("academics.urls")),
    path("api/teachers/", include("teachers.urls")),
    path("api/students/", include("students.urls")),
    path("api/student-attendance/", include("attendance_student.urls")),
    path("api/teacher-attendance/", include("attendance_teacher.urls")),
    path("api/parents/", include("parents.urls")),
    path("api/notifications/", include("notifications.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/system/", include("system.urls")),
    path("api/website/", include("website.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
