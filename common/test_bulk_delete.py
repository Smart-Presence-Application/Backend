"""
POST {app}/bulk-delete/ for students, teachers and schools: who may call
each one, scoping (out-of-scope ids look missing), validation, and
per-item failures that leave the rest deleted. The parent endpoint's
unlink-vs-delete rule is covered in parents/tests.py.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, ClassSection, SchoolClass, Section
from accounts.models import User
from attendance_student.models import AttendanceRecord, AttendanceSession
from common.choices import UserRole
from schools.models import School
from students.models import Student
from teachers.models import Teacher

STUDENTS = "/api/students/bulk-delete/"
TEACHERS = "/api/teachers/bulk-delete/"
SCHOOLS = "/api/schools/bulk-delete/"

# Far above any id the test database will hand out.
MISSING = 10**9


def make_user(email, role):
    user = User(email=email, name=email.split("@")[0], role=role)
    user.set_password("x")
    user.save()
    return user


def make_school(code):
    admin = make_user(f"{code.lower()}-admin@x.com", UserRole.SCHOOL_ADMIN)
    school = School.objects.create(
        name=code, code=code, email=f"{code.lower()}@x.com", phone="9999999999",
        address="a", city="c", state="s", country="in", pincode="1",
        admin=admin,
    )
    return school, admin


def make_section(school, name="A"):
    today = timezone.localdate()
    year, _ = AcademicYear.objects.get_or_create(
        school=school, name="Y",
        defaults={
            "is_active": True,
            "start_date": today - timedelta(days=100),
            "end_date": today + timedelta(days=100),
        },
    )
    school_class, _ = SchoolClass.objects.get_or_create(school=school, name="5")
    return ClassSection.objects.create(
        academic_year=year,
        school_class=school_class,
        section=Section.objects.create(school=school, name=name),
    )


def make_student(section, code):
    return Student.objects.create(
        school=section.academic_year.school, class_section=section,
        name=code, student_id=code, roll_number=code,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class BulkDeleteTests(TestCase):
    def setUp(self):
        self.school, self.school_admin = make_school("SCH")
        self.other_school, _ = make_school("OTH")
        self.section = make_section(self.school)
        self.other_section = make_section(self.other_school)

        self.teacher_user = make_user("t@x.com", UserRole.TEACHER)
        self.teacher = Teacher.objects.create(
            user=self.teacher_user, school=self.school, employee_id="E1",
            class_section=self.section,
        )
        self.other_teacher = Teacher.objects.create(
            user=make_user("t2@x.com", UserRole.TEACHER),
            school=self.other_school, employee_id="E2",
        )

        self.s1 = make_student(self.section, "S1")
        self.s2 = make_student(self.section, "S2")
        self.other_student = make_student(self.other_section, "S3")

        self.super_client = client_for(make_user("super@x.com", UserRole.SUPER_ADMIN))
        self.admin_client = client_for(self.school_admin)
        self.teacher_client = client_for(self.teacher_user)

    def test_roles_allowed_per_endpoint(self):
        body = {"ids": [MISSING]}
        expected = [
            (self.teacher_client, STUDENTS, 200),
            (self.teacher_client, TEACHERS, 403),
            (self.teacher_client, SCHOOLS, 403),
            (self.admin_client, STUDENTS, 200),
            (self.admin_client, TEACHERS, 200),
            (self.admin_client, SCHOOLS, 403),
            (self.super_client, STUDENTS, 200),
            (self.super_client, TEACHERS, 200),
            (self.super_client, SCHOOLS, 200),
        ]

        for client, url, status_code in expected:
            with self.subTest(url=url, status=status_code):
                response = client.post(url, body, format="json")
                self.assertEqual(response.status_code, status_code, response.data)

        self.assertIn(APIClient().post(STUDENTS, body, format="json").status_code, (401, 403))

    def test_school_admin_deletes_own_students_only(self):
        response = self.admin_client.post(
            STUDENTS,
            {"ids": [self.s1.pk, self.other_student.pk, self.s2.pk, self.s1.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["data"],
            {
                "deleted": [self.s1.pk, self.s2.pk],
                "not_found": [self.other_student.pk],
                "failed": [],
            },
        )
        self.assertEqual(response.data["message"], "2 students deleted. 1 not found.")
        self.assertEqual(list(Student.objects.all()), [self.other_student])

    def test_teacher_deletes_only_own_section(self):
        elsewhere = make_student(make_section(self.school, name="B"), "S4")

        response = self.teacher_client.post(
            STUDENTS, {"ids": [self.s1.pk, elsewhere.pk]}, format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["deleted"], [self.s1.pk])
        self.assertEqual(response.data["data"]["not_found"], [elsewhere.pk])
        self.assertTrue(Student.objects.filter(pk=elsewhere.pk).exists())

    def test_referenced_student_fails_without_undoing_the_rest(self):
        session = AttendanceSession.objects.create(
            school=self.school, class_section=self.section, date=timezone.localdate(),
        )
        AttendanceRecord.objects.create(session=session, student=self.s1, status="PRESENT")

        response = self.admin_client.post(
            STUDENTS, {"ids": [self.s1.pk, self.s2.pk]}, format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["deleted"], [self.s2.pk])
        self.assertEqual([f["id"] for f in data["failed"]], [self.s1.pk])
        self.assertTrue(data["failed"][0]["reason"])
        self.assertTrue(Student.objects.filter(pk=self.s1.pk).exists())
        self.assertFalse(Student.objects.filter(pk=self.s2.pk).exists())

    def test_school_admin_deletes_own_teachers_and_their_logins(self):
        response = self.admin_client.post(
            TEACHERS, {"ids": [self.teacher.pk, self.other_teacher.pk]}, format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["deleted"], [self.teacher.pk])
        self.assertEqual(response.data["data"]["not_found"], [self.other_teacher.pk])
        self.assertFalse(User.objects.filter(pk=self.teacher_user.pk).exists())
        self.assertTrue(Teacher.objects.filter(pk=self.other_teacher.pk).exists())

    def test_super_admin_deletes_empty_schools_and_reports_protected_ones(self):
        empty, empty_admin = make_school("EMP")

        response = self.super_client.post(
            SCHOOLS, {"ids": [empty.pk, self.school.pk]}, format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["deleted"], [empty.pk])
        self.assertEqual([f["id"] for f in response.data["data"]["failed"]], [self.school.pk])
        self.assertFalse(School.objects.filter(pk=empty.pk).exists())
        self.assertFalse(User.objects.filter(pk=empty_admin.pk).exists())
        self.assertTrue(School.objects.filter(pk=self.school.pk).exists())

    def test_ids_are_validated(self):
        bad_bodies = [
            {},
            {"ids": []},
            {"ids": 1},
            {"ids": [0]},
            {"ids": ["x"]},
            {"ids": list(range(MISSING, MISSING + 501))},
        ]

        for url in (STUDENTS, TEACHERS, SCHOOLS):
            for body in bad_bodies:
                with self.subTest(url=url, body=str(body)[:30]):
                    response = self.super_client.post(url, body, format="json")
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn("ids", response.data["errors"])

        response = self.super_client.post(
            STUDENTS, {"ids": list(range(MISSING, MISSING + 500))}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]["not_found"]), 500)
