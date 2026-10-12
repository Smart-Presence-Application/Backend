import re
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, ClassSection, SchoolClass, Section
from accounts.models import User
from attendance_student.models import (
    AttendanceRecord,
    AttendanceSession,
)
from common.choices import UserRole
from schools.models import School
from students.models import Student
from teachers.models import Teacher

from .models import Parent, ParentNotification
from .services import generate_parent_password


def make_user(email, role):
    user = User(email=email, name=email.split("@")[0], role=role)
    user.set_password("x")
    user.save()
    return user


class ParentTests(TestCase):
    def setUp(self):
        self.super_admin = make_user("super@x.com", UserRole.SUPER_ADMIN)
        self.school_admin = make_user("admin@x.com", UserRole.SCHOOL_ADMIN)
        self.school = School.objects.create(
            name="School", code="SCH", email="s@x.com", phone="9999999999",
            address="a", city="c", state="s", country="in", pincode="1",
            admin=self.school_admin,
        )
        today = timezone.localdate()
        year = AcademicYear.objects.create(
            school=self.school, name="Y", is_active=True,
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=100),
        )
        school_class = SchoolClass.objects.create(school=self.school, name="5")
        self.section = ClassSection.objects.create(
            academic_year=year, school_class=school_class,
            section=Section.objects.create(school=self.school, name="A"),
        )
        self.other_section = ClassSection.objects.create(
            academic_year=year, school_class=school_class,
            section=Section.objects.create(school=self.school, name="B"),
        )

        self.teacher = make_user("t@x.com", UserRole.TEACHER)
        Teacher.objects.create(
            user=self.teacher, school=self.school, employee_id="E1",
            class_section=self.section,
        )

        self.s1 = Student.objects.create(
            school=self.school, class_section=self.section,
            name="Kid One", student_id="STU1", roll_number="1",
        )
        self.s2 = Student.objects.create(
            school=self.school, class_section=self.other_section,
            name="Kid Two", student_id="STU2", roll_number="1",
        )

        self.teacher_client = APIClient()
        self.teacher_client.force_authenticate(self.teacher)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.school_admin)
        self.super_client = APIClient()
        self.super_client.force_authenticate(self.super_admin)

    def create_parent(self, client, **data):
        payload = {"name": "Atharva Raj Sinha", "phone_number": "9876543210", **data}
        return client.post(reverse("parents:parent-list-create"), payload, format="json")

    def login(self, phone, password):
        client = APIClient()
        response = client.post(
            reverse("parents:login"),
            {"phone_number": phone, "password": password},
            format="json",
        )
        return client, response

    def test_password_format(self):
        self.assertRegex(generate_parent_password("Atharva Raj Sinha"), r"^Atharva@\d{4}$")
        self.assertRegex(generate_parent_password("  riya "), r"^Riya@\d{4}$")

    def test_teacher_creates_parent_and_parent_logs_in_by_mobile(self):
        response = self.create_parent(self.teacher_client, student_id="stu1")

        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        password = data["initial_password"]
        self.assertTrue(re.fullmatch(r"Atharva@\d{4}", password))
        self.assertFalse(data["password_changed"])
        self.assertEqual([s["student_id"] for s in data["students"]], ["STU1"])

        user = User.objects.get(phone_number="9876543210")
        self.assertEqual(user.role, UserRole.PARENT)
        self.assertIsNone(user.email)

        _, bad = self.login("9876543210", "wrong")
        self.assertEqual(bad.status_code, 400)

        client, ok = self.login("9876543210", password)
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertTrue(ok.data["data"]["must_change_password"])
        self.assertIn("access_token", ok.cookies)

    def test_teacher_cannot_create_for_other_section(self):
        response = self.create_parent(self.teacher_client, student_id="STU2")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Parent.objects.exists())

    def test_admin_scopes(self):
        self.assertEqual(
            self.create_parent(self.admin_client, student_id="STU2").status_code, 201,
        )
        self.assertEqual(
            self.create_parent(
                self.super_client, student_id="STU1", phone_number="9000000000",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.create_parent(
                self.super_client, student_id="STU1", phone_number="9000000000",
                school=self.school.pk,
            ).status_code,
            201,
        )

    def test_same_mobile_links_second_child_to_existing_parent(self):
        """The teacher of section A then sees the parent, but only child STU1."""
        first = self.create_parent(self.admin_client, student_id="STU1")
        second = self.create_parent(self.admin_client, student_id="STU2", name="Someone")

        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data["data"]["created"])
        self.assertEqual(Parent.objects.count(), 1)
        self.assertEqual(Parent.objects.get().students.count(), 2)
        self.assertEqual(
            second.data["data"]["initial_password"],
            first.data["data"]["initial_password"],
        )

        listing = self.teacher_client.get(reverse("parents:parent-list-create"))
        students = listing.data["data"]["results"][0]["students"]
        self.assertEqual([s["student_id"] for s in students], ["STU1"])

    def test_password_hidden_after_parent_changes_it_and_reset(self):
        password = self.create_parent(self.teacher_client, student_id="STU1").data["data"][
            "initial_password"
        ]
        parent = Parent.objects.get()
        client, _ = self.login("9876543210", password)

        response = client.post(
            reverse("change-password"),
            {
                "old_password": password,
                "new_password": "My-own-secret-99",
                "confirm_new_password": "My-own-secret-99",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        detail = self.teacher_client.get(
            reverse("parents:parent-detail", args=[parent.pk]),
        ).data["data"]
        self.assertIsNone(detail["initial_password"])
        self.assertTrue(detail["password_changed"])

        reset = self.teacher_client.post(
            reverse("parents:parent-reset-password", args=[parent.pk]),
        )
        new_password = reset.data["data"]["initial_password"]
        self.assertTrue(re.fullmatch(r"Atharva@\d{4}", new_password))
        self.assertEqual(self.login("9876543210", new_password)[1].status_code, 200)

    def test_unlinking_last_child_deletes_parent(self):
        self.create_parent(self.teacher_client, student_id="STU1")
        parent = Parent.objects.get()

        response = self.teacher_client.delete(
            reverse("parents:parent-student-unlink", args=[parent.pk, self.s1.pk]),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["data"]["parent_deleted"])
        self.assertFalse(User.objects.filter(phone_number="9876543210").exists())

    def test_notifications_on_lock_and_admin_change(self):
        """
        Draft edits are not final, so they notify no one and stay hidden.
        Locking notifies the parent; an admin correcting the locked day
        notifies again, while re-saving the same status stays quiet.
        """
        password = self.create_parent(self.teacher_client, student_id="STU1").data["data"][
            "initial_password"
        ]
        parent_client, _ = self.login("9876543210", password)

        session = AttendanceSession.objects.create(
            school=self.school, class_section=self.section, date=timezone.localdate(),
        )
        AttendanceRecord.objects.create(session=session, student=self.s1, status="PRESENT")
        records_url = reverse(
            "attendance_student:attendance-session-records", args=[session.pk],
        )

        self.teacher_client.patch(
            records_url,
            {"records": [{"student": self.s1.pk, "status": "ABSENT"}]},
            format="json",
        )
        self.assertFalse(ParentNotification.objects.exists())
        attendance = parent_client.get(reverse("parents:me-attendance"))
        self.assertEqual(attendance.data["data"]["count"], 0)

        with self.captureOnCommitCallbacks(execute=True):
            self.teacher_client.post(
                reverse("attendance_student:attendance-session-lock", args=[session.pk]),
            )

        notifications = parent_client.get(reverse("parents:me-notifications"))
        results = notifications.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "ABSENT")
        self.assertIn("Kid One", results[0]["message"])

        attendance = parent_client.get(reverse("parents:me-attendance"))
        self.assertEqual(attendance.data["data"]["results"][0]["status"], "ABSENT")

        with self.captureOnCommitCallbacks(execute=True):
            self.admin_client.patch(
                records_url,
                {"records": [{"student": self.s1.pk, "status": "PRESENT"}]},
                format="json",
            )
            self.admin_client.patch(
                records_url,
                {"records": [{"student": self.s1.pk, "status": "PRESENT"}]},
                format="json",
            )

        self.assertEqual(ParentNotification.objects.count(), 2)
        latest = ParentNotification.objects.order_by("-created_at").first()
        self.assertTrue(latest.title.startswith("Attendance updated"))

        unread = parent_client.get(reverse("parents:me-notifications-unread-count"))
        self.assertEqual(unread.data["data"]["unread"], 2)
        parent_client.post(reverse("parents:me-notifications-read"), {}, format="json")
        unread = parent_client.get(reverse("parents:me-notifications-unread-count"))
        self.assertEqual(unread.data["data"]["unread"], 0)

    def test_parents_cannot_use_staff_routes(self):
        password = self.create_parent(self.teacher_client, student_id="STU1").data["data"][
            "initial_password"
        ]
        parent_client, _ = self.login("9876543210", password)

        self.assertEqual(
            parent_client.get(reverse("parents:parent-list-create")).status_code, 403,
        )
        self.assertEqual(
            parent_client.get(reverse("students:student-list-create")).status_code, 403,
        )

    def upload(self, client, csv_text, **data):
        from django.core.files.uploadedfile import SimpleUploadedFile

        file = SimpleUploadedFile("parents.csv", csv_text.encode(), content_type="text/csv")
        return client.post(reverse("parents:parent-bulk-upload"), {"file": file, **data}, format="multipart")

    def test_bulk_upload_creates_links_and_reuses_parents(self):
        """
        One file creates a parent with two children and gives an existing
        parent a second child. New parents come back with the password to
        hand over, and uploading the same file again changes nothing.
        """
        Student.objects.create(
            school=self.school, class_section=self.section,
            name="Kid Three", student_id="STU3", roll_number="3",
        )
        self.create_parent(self.admin_client, student_id="STU2", phone_number="9000000009", name="Existing Parent")

        response = self.upload(
            self.admin_client,
            "Student ID,Name,Phone Number\n"
            "stu1,Riya Sharma,9111111111\n"
            "STU3,Riya Sharma,9111111111\n"
            "STU1,Existing Parent,9000000009\n",
        )

        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        self.assertEqual((data["created"], data["linked"], data["already_linked"]), (1, 2, 0))
        riya = Parent.objects.get(user__phone_number="9111111111")
        self.assertEqual(set(riya.students.values_list("student_id", flat=True)), {"STU1", "STU3"})
        self.assertEqual(
            set(Parent.objects.get(user__phone_number="9000000009").students.values_list("student_id", flat=True)),
            {"STU1", "STU2"},
        )
        created = next(p for p in data["parents"] if p["phone_number"] == "9111111111")
        self.assertRegex(created["initial_password"], r"^Riya@\d{4}$")

        again = self.upload(self.admin_client, "student_id,name,phone_number\nSTU1,Riya Sharma,9111111111\n")
        self.assertEqual(again.data["data"]["already_linked"], 1)
        self.assertEqual(Parent.objects.filter(user__phone_number="9111111111").count(), 1)

    def test_bulk_upload_reports_every_bad_row_and_saves_nothing(self):
        """Rows: 2 bad number, 3 another class, 5 repeated row, 6 one number with two names."""
        response = self.upload(
            self.teacher_client,
            "student_id,name,phone_number\n"
            "STU1,Riya Sharma,12345\n"
            "STU2,Other,9222222222\n"
            "STU1,Riya Sharma,9333333333\n"
            "STU1,Riya Sharma,9333333333\n"
            "STU1,Someone Else,9333333333\n",
        )

        self.assertEqual(response.status_code, 400)
        errors = response.data["errors"]
        self.assertIn("phone_number", errors["2"])
        self.assertIn("student_id", errors["3"])
        self.assertIn("student_id", errors["5"])
        self.assertIn("name", errors["6"])
        self.assertFalse(Parent.objects.exists())

    def test_bulk_upload_file_and_scope_checks(self):
        missing = self.upload(self.admin_client, "student_id,name\nSTU1,Riya\n")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("file", missing.data["errors"])

        no_school = self.upload(self.super_client, "student_id,name,phone_number\nSTU1,Riya,9111111111\n")
        self.assertEqual(no_school.status_code, 400)
        with_school = self.upload(
            self.super_client, "student_id,name,phone_number\nSTU1,Riya,9111111111\n", school=self.school.pk,
        )
        self.assertEqual(with_school.status_code, 201, with_school.data)

        staff_number = make_user("staff@x.com", UserRole.TEACHER)
        staff_number.phone_number = "9444444444"
        staff_number.save()
        clash = self.upload(self.admin_client, "student_id,name,phone_number\nSTU2,Riya,9444444444\n")
        self.assertEqual(clash.status_code, 400)
        self.assertIn("phone_number", clash.data["errors"]["2"])
