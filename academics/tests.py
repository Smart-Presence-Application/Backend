from datetime import date

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from common.choices import DayType, UserRole
from parents.models import Parent
from schools.models import School
from students.models import Student
from teachers.models import Teacher

from .models import AcademicYear, ClassSection, Holiday, SchoolClass, Section, WorkingDay


def make_user(email, role, phone=None):
    user = User(email=email, name=(email or phone).split("@")[0], role=role)
    if phone:
        user.phone_number = phone
    user.set_password("x")
    user.save()
    return user


def make_school(code, admin):
    return School.objects.create(
        name=f"School {code}", code=code, email=f"{code}@x.com", phone="9999999999",
        address="a", city="c", state="s", country="in", pincode="1", admin=admin,
    )


class SchoolCalendarTests(TestCase):
    def setUp(self):
        """School A has a full calendar; school B has one entry that must never leak."""
        self.admin_a = make_user("a@x.com", UserRole.SCHOOL_ADMIN)
        self.admin_b = make_user("b@x.com", UserRole.SCHOOL_ADMIN)
        self.school_a = make_school("A", self.admin_a)
        self.school_b = make_school("B", self.admin_b)
        self.year = AcademicYear.objects.create(
            school=self.school_a, name="2026-27", is_active=True,
            start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
        )
        WorkingDay.objects.create(school=self.school_a, academic_year=self.year, date=date(2026, 10, 5), day_type=DayType.WORKING)
        WorkingDay.objects.create(school=self.school_a, academic_year=self.year, date=date(2026, 10, 11), day_type=DayType.WEEKEND, remarks="Sunday")
        WorkingDay.objects.create(school=self.school_a, academic_year=self.year, date=date(2026, 10, 15), day_type=DayType.EVENT, remarks="Sports day")
        Holiday.objects.create(school=self.school_a, academic_year=self.year, title="Dussehra", date=date(2026, 10, 20))
        other_year = AcademicYear.objects.create(school=self.school_b, name="Y", start_date=date(2026, 6, 1), end_date=date(2027, 3, 31))
        WorkingDay.objects.create(school=self.school_b, academic_year=other_year, date=date(2026, 10, 6), day_type=DayType.HOLIDAY)

        section = ClassSection.objects.create(
            academic_year=self.year,
            school_class=SchoolClass.objects.create(school=self.school_a, name="5"),
            section=Section.objects.create(school=self.school_a, name="A"),
        )
        self.teacher = make_user("t@x.com", UserRole.TEACHER)
        Teacher.objects.create(user=self.teacher, school=self.school_a, employee_id="E1", class_section=section)

        student = Student.objects.create(school=self.school_a, class_section=section, name="Kid", student_id="S1", roll_number="1")
        self.parent = make_user(None, UserRole.PARENT, phone="9000000001")
        Parent.objects.create(user=self.parent).students.add(student)

    def get(self, user, **params):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(reverse("academics:calendar"), {"date_from": "2026-10-01", "date_to": "2026-10-31", **params})

    def test_every_role_sees_its_own_school_calendar(self):
        for user in (self.admin_a, self.teacher, self.parent):
            response = self.get(user)
            self.assertEqual(response.status_code, 200, response.data)
            data = response.data["data"]
            self.assertEqual(data["school"], self.school_a.id)
            self.assertEqual(data["academic_year"]["name"], "2026-27")
            by_date = {str(d["date"]): d for d in data["days"]}
            self.assertEqual(
                {k: v["day_type"] for k, v in by_date.items()},
                {"2026-10-05": "WORKING", "2026-10-11": "WEEKEND", "2026-10-15": "EVENT", "2026-10-20": "HOLIDAY"},
            )
            self.assertEqual(by_date["2026-10-20"]["title"], "Dussehra")
            self.assertEqual(by_date["2026-10-15"]["remarks"], "Sports day")

    def test_cannot_read_another_school(self):
        self.assertEqual(self.get(self.teacher, school=self.school_b.id).status_code, 404)
        self.assertEqual(self.get(self.parent, school=self.school_b.id).status_code, 404)

    def test_super_admin_names_the_school_and_range_is_checked(self):
        super_admin = make_user("s@x.com", UserRole.SUPER_ADMIN)
        self.assertEqual(self.get(super_admin).status_code, 400)
        response = self.get(super_admin, school=self.school_b.id)
        self.assertEqual([d["day_type"] for d in response.data["data"]["days"]], ["HOLIDAY"])

        backwards = self.get(self.teacher, date_from="2026-10-31", date_to="2026-10-01")
        self.assertEqual(backwards.status_code, 400)
        too_long = self.get(self.teacher, date_from="2026-01-01", date_to="2027-06-01")
        self.assertEqual(too_long.status_code, 400)
