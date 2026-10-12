"""Reusable model choices."""
from django.db import models

class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    SCHOOL_ADMIN = "SCHOOL_ADMIN", "School Admin"
    TEACHER = "TEACHER", "Teacher"
    PARENT = "PARENT", "Parent"


class Gender(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHER = "OTHER", "Other"


class AttendanceStatus(models.TextChoices):
    PRESENT = "PRESENT", "Present"
    ABSENT = "ABSENT", "Absent"


class DayType(models.TextChoices):
    WORKING = "WORKING", "Working Day"
    HOLIDAY = "HOLIDAY", "Holiday"
    WEEKEND = "WEEKEND", "Weekend"
    EVENT = "EVENT", "Event"


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Monday"
    TUESDAY = 1, "Tuesday"
    WEDNESDAY = 2, "Wednesday"
    THURSDAY = 3, "Thursday"
    FRIDAY = 4, "Friday"
    SATURDAY = 5, "Saturday"
    SUNDAY = 6, "Sunday"


class Status(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"