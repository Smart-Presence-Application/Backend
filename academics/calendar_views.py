"""
A read-only school calendar for every signed-in role.

The academic endpoints are for administrators; this one lets teachers
and parents see the same calendar (working days, events, holidays and
weekends) for their own school, without being able to change it.
"""

from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated

from common.choices import DayType, UserRole
from common.responses import success_response
from schools.models import School

from .models import AcademicYear, Holiday, WorkingDay

MAX_RANGE_DAYS = 366


class CalendarParamsSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    school = serializers.PrimaryKeyRelatedField(queryset=School.objects.all(), required=False)

    def validate(self, attrs):
        if attrs["date_to"] < attrs["date_from"]:
            raise serializers.ValidationError({"date_to": "Must be on or after date_from."})

        if (attrs["date_to"] - attrs["date_from"]).days >= MAX_RANGE_DAYS:
            raise serializers.ValidationError({"date_to": f"The range can cover at most {MAX_RANGE_DAYS} days."})

        return attrs


def schools_for(user) -> list[School]:
    """
    The schools whose calendar ``user`` may read.

    A Super Admin gets an empty list because they name any school
    explicitly. A parent may have children in more than one school.
    """

    if user.role == UserRole.SUPER_ADMIN:
        return []

    if user.role == UserRole.SCHOOL_ADMIN:
        school = getattr(user, "managed_school", None)
        return [school] if school else []

    if user.role == UserRole.TEACHER:
        profile = getattr(user, "teacher_profile", None)
        return [profile.school] if profile and profile.school_id else []

    if user.role == UserRole.PARENT:
        profile = getattr(user, "parent_profile", None)
        if profile is None:
            return []
        return list(School.objects.filter(students__parents=profile).distinct().order_by("name"))

    return []


class SchoolCalendarAPIView(generics.GenericAPIView):
    """
    ``GET /academics/calendar/?date_from=&date_to=[&school=]``

    Every date in the range that the school has marked, with its type and
    label. A holiday's title labels its date, whatever the working-day
    row says. Dates with no entry are left out;
    the school has not set them. Super Admins name the school; parents
    with children in several schools may pick one of them.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        params = CalendarParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        user = request.user

        if user.role == UserRole.SUPER_ADMIN:
            school = data.get("school")
            if school is None:
                raise ValidationError({"school": "This field is required when acting as a Super Admin."})
            choices = [school]
        else:
            choices = schools_for(user)
            if not choices:
                raise NotFound("You are not linked to a school yet.")
            school = data.get("school") or choices[0]
            if school not in choices:
                raise NotFound("School not found.")

        date_from, date_to = data["date_from"], data["date_to"]

        days: dict = {}
        for wd in WorkingDay.objects.filter(school=school, date__range=(date_from, date_to)):
            days[wd.date] = {"date": wd.date, "day_type": wd.day_type, "title": "", "remarks": wd.remarks}

        for holiday in Holiday.objects.filter(school=school, date__range=(date_from, date_to)):
            entry = days.setdefault(holiday.date, {"date": holiday.date, "remarks": ""})
            entry.update(day_type=DayType.HOLIDAY, title=holiday.title, remarks=holiday.description or entry.get("remarks", ""))

        year = (
            AcademicYear.objects.filter(school=school, start_date__lte=date_to, end_date__gte=date_from)
            .order_by("-is_active", "-start_date")
            .first()
        )

        return success_response(
            "Calendar fetched successfully.",
            {
                "school": school.id,
                "school_name": school.name,
                "schools": [{"id": s.id, "name": s.name} for s in choices],
                "date_from": date_from,
                "date_to": date_to,
                "academic_year": (
                    {"id": year.id, "name": year.name, "start_date": year.start_date, "end_date": year.end_date} if year else None
                ),
                "days": [days[d] for d in sorted(days)],
            },
        )

