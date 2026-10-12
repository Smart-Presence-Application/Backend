from django.apps import AppConfig


class AttendanceStudentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attendance_student"
    verbose_name = "Student Attendance"

    def ready(self):
        import attendance_student.signals  # noqa: F401
