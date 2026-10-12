import io
import shutil
import threading
import time
import tempfile
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from academics.models import AcademicYear, ClassSection, Holiday, SchoolClass, Section, WorkingDay
from accounts.models import User
from common.choices import DayType, UserRole
from schools.models import School
from students.models import Student
from teachers.models import Teacher

from .models import (
    AIJob,
    AIJobKind,
    AIJobStatus,
    AttendanceRecord,
    AttendanceSession,
    FaceRegistration,
    FaceRegistrationSource,
    RecordSource,
    SessionStatus,
)

MEDIA_ROOT = tempfile.mkdtemp()


def image_file(name="photo.jpg"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def make_user(email, role):
    user = User(email=email, name=email.split("@")[0], role=role)
    user.set_password("x")
    user.save()
    return user


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class AttendanceFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.super_admin = make_user("super@x.com", UserRole.SUPER_ADMIN)
        self.school_admin = make_user("admin@x.com", UserRole.SCHOOL_ADMIN)
        self.school = School.objects.create(
            name="School", code="SCH", email="s@x.com", phone="9999999999",
            address="a", city="c", state="s", country="in", pincode="1",
            admin=self.school_admin,
        )
        today = timezone.localdate()
        self.year = AcademicYear.objects.create(
            school=self.school, name="Y", is_active=True,
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=100),
        )
        school_class = SchoolClass.objects.create(school=self.school, name="5")
        section_a = Section.objects.create(school=self.school, name="A")
        section_b = Section.objects.create(school=self.school, name="B")
        self.section = ClassSection.objects.create(
            academic_year=self.year, school_class=school_class, section=section_a,
        )
        self.other_section = ClassSection.objects.create(
            academic_year=self.year, school_class=school_class, section=section_b,
        )

        self.teacher = make_user("t@x.com", UserRole.TEACHER)
        Teacher.objects.create(
            user=self.teacher, school=self.school, employee_id="E1",
            class_section=self.section,
        )
        self.other_teacher = make_user("t2@x.com", UserRole.TEACHER)
        Teacher.objects.create(
            user=self.other_teacher, school=self.school, employee_id="E2",
            class_section=self.other_section,
        )

        self.s1 = Student.objects.create(
            school=self.school, class_section=self.section,
            name="One", student_id="STU1", roll_number="1",
        )
        self.s2 = Student.objects.create(
            school=self.school, class_section=self.section,
            name="Two", student_id="STU2", roll_number="2",
        )
        self.s3 = Student.objects.create(
            school=self.school, class_section=self.section,
            name="Three", student_id="STU3", roll_number="3",
        )

        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

        patcher = mock.patch("attendance_student.services.ai_client")
        self.ai = patcher.start()
        self.addCleanup(patcher.stop)
        self.ai.register_face.return_value = {"status": "success"}
        self.ai.delete_face.return_value = True

    def register(self, *students):
        for student in students:
            FaceRegistration.objects.create(
                student=student, source=FaceRegistrationSource.UPLOAD,
            )

    def verify(self, client=None, **extra):
        self.ai.verify_attendance.return_value = {
            "image_count": 1,
            "detected_faces": 2,
            "matches": [{"student_id": "STU1", "similarity": 0.81}],
            "students": [
                {"student_id": "STU1", "status": "Present"},
                {"student_id": "STU2", "status": "Absent"},
            ],
        }
        return (client or self.client).post(
            reverse("attendance_student:attendance-verify"),
            {"images": [image_file()], **extra},
            format="multipart",
        )

    def poll(self, job_id, client=None):
        return (client or self.client).get(
            reverse("attendance_student:ai-job-detail", args=[job_id]),
        )

    def verified_session(self, response):
        """The session a finished verification job saved, as the API shows it."""

        self.assertEqual(response.status_code, 202, response.data)
        job = response.data["data"]
        self.assertEqual(job["status"], AIJobStatus.SUCCEEDED, job)
        detail = self.client.get(
            reverse(
                "attendance_student:attendance-session-detail",
                args=[job["result"]["session"]],
            ),
        )
        self.assertEqual(detail.status_code, 200, detail.data)
        return detail.data["data"]

    def test_bulk_register_matches_files_by_student_id(self):
        response = self.client.post(
            reverse("attendance_student:face-register"),
            {
                "images": [
                    image_file("stu1.jpg"),
                    image_file("STU2.png"),
                    image_file("NOPE.jpg"),
                ]
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)
        job = response.data["data"]
        self.assertEqual(job["kind"], AIJobKind.FACE_REGISTER)
        self.assertEqual(job["status"], AIJobStatus.SUCCEEDED)
        self.assertTrue(job["done"])
        self.assertEqual((job["total"], job["processed"]), (3, 3))
        self.assertEqual(job["result"]["registered"], 2)
        self.assertEqual(job["result"]["failed"], 1)
        self.assertEqual(self.ai.register_face.call_count, 2)
        self.ai.register_face.assert_any_call(
            school_id=self.school.id, student_id="STU1", image=mock.ANY,
        )
        self.s1.refresh_from_db()
        self.assertTrue(self.s1.has_profile_image)
        self.assertTrue(FaceRegistration.objects.filter(student=self.s1).exists())

    def test_single_register_by_student_ignores_file_name(self):
        response = self.client.post(
            reverse("attendance_student:face-register"),
            {"student": self.s3.pk, "images": [image_file("whatever.jpg")]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data["data"]["result"]["registered"], 1)
        self.assertTrue(FaceRegistration.objects.filter(student=self.s3).exists())

    def test_teacher_cannot_register_other_section_student(self):
        other = Student.objects.create(
            school=self.school, class_section=self.other_section,
            name="X", student_id="OTH", roll_number="1",
        )
        response = self.client.post(
            reverse("attendance_student:face-register"),
            {"images": [image_file("OTH.jpg")]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(FaceRegistration.objects.filter(student=other).exists())
        self.ai.register_face.assert_not_called()

    def test_ai_rejection_is_reported_per_file(self):
        from .ai_client import AIServiceError

        self.ai.register_face.side_effect = AIServiceError("No face detected.", 422)
        response = self.client.post(
            reverse("attendance_student:face-register"),
            {"images": [image_file("STU1.jpg")]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)
        result = response.data["data"]["result"]
        self.assertEqual(result["registered"], 0)
        self.assertEqual(result["results"][0]["error"], "No face detected.")
        self.s1.refresh_from_db()
        self.assertFalse(self.s1.has_profile_image)

    def test_register_from_existing_profile_image(self):
        self.s1.profile_image = image_file("p.jpg")
        self.s1.save()

        response = self.client.post(
            reverse("attendance_student:face-register-from-profile"),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 202, response.data)
        job = response.data["data"]
        self.assertEqual(job["kind"], AIJobKind.FACE_REGISTER_FROM_PROFILE)
        self.assertEqual(job["result"]["registered"], 1)
        registration = FaceRegistration.objects.get(student=self.s1)
        self.assertEqual(registration.source, FaceRegistrationSource.PROFILE_IMAGE)

    def change_photo(self, student, name="new.jpg"):
        return self.client.patch(
            reverse("students:student-profile-image", args=[student.pk]),
            {"profile_image": image_file(name)},
            format="multipart",
        )

    def test_new_profile_photo_is_registered_as_face(self):
        self.register(self.s1)

        with mock.patch("attendance_student.signals.ai_client") as signal_ai:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.change_photo(self.s1)

        self.assertEqual(response.status_code, 202, response.data)
        self.assertTrue(response.data["data"]["face_registered"])
        face_job = response.data["data"]["face_job"]
        self.assertEqual(face_job["status"], AIJobStatus.SUCCEEDED)
        self.assertTrue(face_job["result"]["face_registered"])
        self.ai.register_face.assert_called_once_with(
            school_id=self.school.id, student_id="STU1", image=mock.ANY,
        )
        registration = FaceRegistration.objects.get(student=self.s1)
        self.assertEqual(registration.source, FaceRegistrationSource.UPLOAD)
        self.s1.refresh_from_db()
        self.assertTrue(self.s1.has_profile_image)
        signal_ai.delete_face_quietly.assert_not_called()

    def test_rejected_profile_photo_keeps_old_photo_and_face(self):
        from .ai_client import AIServiceError

        self.s1.profile_image = image_file("old.jpg")
        self.s1.save()
        self.register(self.s1)
        old_name = self.s1.profile_image.name

        self.ai.register_face.side_effect = AIServiceError("No face detected.", 422)
        response = self.change_photo(self.s1)

        self.assertEqual(response.status_code, 202, response.data)
        face_job = response.data["data"]["face_job"]
        self.assertEqual(face_job["status"], AIJobStatus.FAILED)
        self.assertEqual(face_job["error"], "No face detected.")
        self.assertEqual(face_job["error_status"], 400)
        self.assertEqual(face_job["errors"], {"ai_service": "No face detected."})
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.profile_image.name, old_name)
        self.assertTrue(FaceRegistration.objects.filter(student=self.s1).exists())

    def test_profile_photo_saved_when_ai_down_but_stale_face_dropped(self):
        from common.exceptions import AIServiceUnavailable

        self.register(self.s1)
        self.ai.register_face.side_effect = AIServiceUnavailable()

        with mock.patch("attendance_student.signals.ai_client") as signal_ai:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.change_photo(self.s1)

        self.assertEqual(response.status_code, 202, response.data)
        self.assertFalse(response.data["data"]["face_registered"])
        self.assertFalse(response.data["data"]["face_job"]["result"]["face_registered"])
        self.s1.refresh_from_db()
        self.assertTrue(self.s1.has_profile_image)
        self.assertFalse(FaceRegistration.objects.filter(student=self.s1).exists())
        signal_ai.delete_face_quietly.assert_called_once_with(
            school_id=self.school.id, student_id="STU1",
        )

    def test_enrolment_photo_is_registered_as_face(self):
        response = self.client.post(
            reverse("students:student-list-create"),
            {"name": "Four", "student_id": "stu4", "roll_number": "4",
             "profile_image": image_file("four.jpg")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["face_job"]["status"], AIJobStatus.SUCCEEDED)
        student = Student.objects.get(student_id="STU4")
        self.assertTrue(student.has_profile_image)
        self.assertTrue(FaceRegistration.objects.filter(student=student).exists())

    def test_enrolment_with_rejected_photo_keeps_student_without_photo(self):
        """The face is checked in the background, so enrolment stands and the job reports the rejection."""
        from .ai_client import AIServiceError

        self.ai.register_face.side_effect = AIServiceError("No face detected.", 422)
        response = self.client.post(
            reverse("students:student-list-create"),
            {"name": "Four", "student_id": "STU4", "roll_number": "4",
             "profile_image": image_file("four.jpg")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["face_job"]["status"], AIJobStatus.FAILED)
        student = Student.objects.get(student_id="STU4")
        self.assertFalse(student.has_profile_image)
        self.assertFalse(FaceRegistration.objects.filter(student=student).exists())

    def test_student_id_change_and_delete_remove_face(self):
        self.register(self.s1, self.s2)
        self.client.force_authenticate(self.school_admin)

        with mock.patch("attendance_student.signals.ai_client") as signal_ai:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.patch(
                    reverse("students:student-detail", args=[self.s1.pk]),
                    {"student_id": "NEW1"},
                    format="json",
                )
                self.client.delete(
                    reverse("students:student-detail", args=[self.s2.pk]),
                )

        signal_ai.delete_face_quietly.assert_has_calls(
            [
                mock.call(school_id=self.school.id, student_id="STU1"),
                mock.call(school_id=self.school.id, student_id="STU2"),
            ]
        )
        self.assertFalse(FaceRegistration.objects.exists())

    def test_explicit_delete_face(self):
        self.register(self.s1)

        response = self.client.delete(
            reverse("attendance_student:face-delete", args=[self.s1.pk]),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.ai.delete_face.assert_called_once_with(
            school_id=self.school.id, student_id="STU1",
        )
        self.assertFalse(FaceRegistration.objects.exists())

    def test_face_status_list(self):
        self.register(self.s1)

        response = self.client.get(
            reverse("attendance_student:face-list"), {"registered": "false"},
        )

        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["student_id"] for row in response.data["data"]["results"]]
        self.assertEqual(ids, ["STU2", "STU3"])

    def test_verify_creates_draft_for_class_section(self):
        self.register(self.s1, self.s2)

        response = self.verify()

        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data["data"]["kind"], AIJobKind.ATTENDANCE_VERIFY)
        self.ai.verify_attendance.assert_called_once_with(
            school_id=self.school.id,
            student_ids=["STU1", "STU2"],
            images=mock.ANY,
        )
        data = self.verified_session(response)
        self.assertEqual(data["status"], SessionStatus.DRAFT)
        self.assertEqual(data["present_count"], 1)
        self.assertEqual(data["not_registered_count"], 1)
        by_id = {r["student_id"]: r for r in data["records"]}
        self.assertEqual(by_id["STU1"]["status"], "PRESENT")
        self.assertEqual(by_id["STU1"]["similarity"], 0.81)
        self.assertEqual(by_id["STU2"]["status"], "ABSENT")
        self.assertEqual(by_id["STU3"]["status"], "ABSENT")
        self.assertIsNone(by_id["STU3"]["ai_status"])
        self.assertFalse(by_id["STU3"]["face_registered"])

    def test_verify_without_any_registered_face_is_rejected(self):
        response = self.verify()

        self.assertEqual(response.status_code, 400)
        self.ai.verify_attendance.assert_not_called()

    def test_verify_rejects_future_date_and_holiday(self):
        self.register(self.s1)
        today = timezone.localdate()
        Holiday.objects.create(
            school=self.school, academic_year=self.year, title="H", date=today,
        )

        self.assertEqual(self.verify(date=today + timedelta(days=1)).status_code, 400)
        self.assertEqual(self.verify(date=today).status_code, 400)

    def test_full_teacher_workflow_and_lock(self):
        """A manual correction survives an AI re-run; once locked, only an admin can edit or unlock."""
        self.register(self.s1, self.s2)
        session_id = self.verified_session(self.verify())["id"]
        records_url = reverse(
            "attendance_student:attendance-session-records", args=[session_id],
        )

        response = self.client.patch(
            records_url,
            {"records": [{"student": self.s2.pk, "status": "PRESENT"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.verify()
        record = AttendanceRecord.objects.get(session_id=session_id, student=self.s2)
        self.assertEqual(record.status, "PRESENT")
        self.assertEqual(record.source, RecordSource.MANUAL)
        self.assertEqual(record.ai_status, "ABSENT")

        response = self.client.post(
            reverse("attendance_student:attendance-session-lock", args=[session_id]),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], SessionStatus.LOCKED)

        response = self.client.patch(
            records_url,
            {"records": [{"student": self.s1.pk, "status": "ABSENT"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.verify().status_code, 409)
        self.assertEqual(
            self.client.post(
                reverse("attendance_student:attendance-session-unlock", args=[session_id]),
            ).status_code,
            403,
        )

        admin = APIClient()
        admin.force_authenticate(self.school_admin)
        response = admin.patch(
            records_url,
            {"records": [{"student": self.s1.pk, "status": "ABSENT", "remarks": "left early"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            AttendanceSession.objects.get(pk=session_id).status, SessionStatus.LOCKED,
        )
        response = admin.post(
            reverse("attendance_student:attendance-session-unlock", args=[session_id]),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], SessionStatus.DRAFT)

    def test_admins_must_name_scope(self):
        self.register(self.s1)
        admin = APIClient()
        admin.force_authenticate(self.school_admin)
        self.assertEqual(self.verify(client=admin).status_code, 400)
        self.assertEqual(
            self.verify(client=admin, class_section=self.section.pk).status_code, 202,
        )

        sup = APIClient()
        sup.force_authenticate(self.super_admin)
        self.assertEqual(
            self.verify(client=sup, class_section=self.section.pk).status_code, 400,
        )
        self.assertEqual(
            self.verify(
                client=sup, school=self.school.pk, class_section=self.section.pk,
            ).status_code,
            202,
        )

    def test_manual_session_and_scoping(self):
        response = self.client.post(
            reverse("attendance_student:attendance-session-list-create"),
            {"records": [{"student": self.s1.pk, "status": "PRESENT"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        self.assertEqual(data["total_students"], 3)
        self.assertEqual(data["present_count"], 1)

        listing = self.client.get(
            reverse("attendance_student:attendance-session-list-create"),
        )
        self.assertEqual(listing.data["data"]["count"], 1)
        self.assertEqual(listing.data["data"]["results"][0]["present_count"], 1)

        other = APIClient()
        other.force_authenticate(self.other_teacher)
        response = other.get(
            reverse("attendance_student:attendance-session-detail", args=[data["id"]]),
        )
        self.assertEqual(response.status_code, 404)

    def test_only_admins_can_delete_attendance(self):
        session = AttendanceSession.objects.create(
            school=self.school, class_section=self.section,
            date=timezone.localdate(), status=SessionStatus.LOCKED,
        )
        AttendanceRecord.objects.create(session=session, student=self.s1, status="PRESENT")
        url = reverse("attendance_student:attendance-session-detail", args=[session.pk])

        self.assertEqual(self.client.delete(url).status_code, 403)

        admin = APIClient()
        admin.force_authenticate(self.school_admin)
        response = admin.delete(url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(AttendanceSession.objects.filter(pk=session.pk).exists())
        self.assertFalse(AttendanceRecord.objects.filter(session_id=session.pk).exists())
        self.assertEqual(admin.delete(url).status_code, 404)

        session = AttendanceSession.objects.create(
            school=self.school, class_section=self.section, date=timezone.localdate(),
        )
        super_admin = APIClient()
        super_admin.force_authenticate(self.super_admin)
        response = super_admin.delete(
            reverse("attendance_student:attendance-session-detail", args=[session.pk]),
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_taking_attendance_marks_the_day_as_working(self):
        """Attendance on an unset date marks it working; a second class leaves the entry as it is."""
        today = timezone.localdate()

        response = self.client.post(
            reverse("attendance_student:attendance-session-list-create"), {}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        day = WorkingDay.objects.get(school=self.school, date=today)
        self.assertEqual(day.day_type, DayType.WORKING)
        self.assertEqual(day.academic_year, self.year)

        other = APIClient()
        other.force_authenticate(self.other_teacher)
        Student.objects.create(school=self.school, class_section=self.other_section, name="Four", student_id="STU4", roll_number="1")
        other.post(reverse("attendance_student:attendance-session-list-create"), {}, format="json")
        self.assertEqual(WorkingDay.objects.filter(school=self.school, date=today).count(), 1)

    def test_ai_attendance_marks_working_day_but_keeps_events(self):
        self.register(self.s1)
        yesterday = timezone.localdate() - timedelta(days=1)
        WorkingDay.objects.create(
            school=self.school, academic_year=self.year, date=yesterday,
            day_type=DayType.EVENT, remarks="Sports day",
        )

        self.assertEqual(self.verify(date=yesterday).status_code, 202)
        event = WorkingDay.objects.get(school=self.school, date=yesterday)
        self.assertEqual((event.day_type, event.remarks), (DayType.EVENT, "Sports day"))

        self.assertEqual(self.verify().status_code, 202)
        self.assertEqual(WorkingDay.objects.get(school=self.school, date=timezone.localdate()).day_type, DayType.WORKING)

    def test_holidays_are_never_turned_into_working_days(self):
        today = timezone.localdate()
        WorkingDay.objects.create(school=self.school, academic_year=self.year, date=today, day_type=DayType.HOLIDAY)

        response = self.client.post(
            reverse("attendance_student:attendance-session-list-create"), {}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WorkingDay.objects.get(school=self.school, date=today).day_type, DayType.HOLIDAY)

    def test_verify_rejected_by_ai_fails_the_job(self):
        from .ai_client import AIServiceError

        self.register(self.s1)
        self.ai.verify_attendance.side_effect = AIServiceError("Images are unreadable.", 422)
        response = self.client.post(
            reverse("attendance_student:attendance-verify"),
            {"images": [image_file()]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)
        job = response.data["data"]
        self.assertEqual(job["status"], AIJobStatus.FAILED)
        self.assertEqual(job["error_status"], 400)
        self.assertEqual(job["errors"], {"ai_service": "Images are unreadable."})
        self.assertFalse(AttendanceSession.objects.exists())

    def test_verify_with_ai_down_fails_the_job_with_503(self):
        from common.exceptions import AIServiceUnavailable

        self.register(self.s1)
        self.ai.verify_attendance.side_effect = AIServiceUnavailable()
        response = self.client.post(
            reverse("attendance_student:attendance-verify"),
            {"images": [image_file()]},
            format="multipart",
        )

        job = response.data["data"]
        self.assertEqual(job["status"], AIJobStatus.FAILED)
        self.assertEqual(job["error_status"], 503)

    def test_job_can_be_polled_by_its_owner_only(self):
        self.register(self.s1)
        job_id = self.verify().data["data"]["id"]

        response = self.poll(job_id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], AIJobStatus.SUCCEEDED)
        self.assertEqual(response.data["data"]["percent"], 100)
        self.assertIsNone(response.data["data"]["poll_after"])

        other = APIClient()
        other.force_authenticate(self.other_teacher)
        self.assertEqual(self.poll(job_id, client=other).status_code, 404)

        sup = APIClient()
        sup.force_authenticate(self.super_admin)
        self.assertEqual(self.poll(job_id, client=sup).status_code, 200)

    def test_second_verification_of_same_day_waits_for_the_first(self):
        self.register(self.s1)
        AIJob.objects.create(
            kind=AIJobKind.ATTENDANCE_VERIFY, created_by=self.teacher,
            class_section=self.section, date=timezone.localdate(),
        )

        response = self.verify()

        self.assertEqual(response.status_code, 409, response.data)
        self.ai.verify_attendance.assert_not_called()

    def test_stale_job_is_reported_failed_and_no_longer_blocks(self):
        job = AIJob.objects.create(
            kind=AIJobKind.ATTENDANCE_VERIFY, created_by=self.teacher,
            status=AIJobStatus.RUNNING,
            class_section=self.section, date=timezone.localdate(),
        )
        AIJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(days=1),
        )

        self.register(self.s1)
        self.assertEqual(self.verify().status_code, 202)

        response = self.poll(job.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], AIJobStatus.FAILED)
        self.assertTrue(response.data["data"]["done"])

    def test_files_matching_no_student_are_refused_at_once(self):
        response = self.client.post(
            reverse("attendance_student:face-register"),
            {"images": [image_file("NOPE.jpg")]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["errors"]["failed"], 1)
        self.assertFalse(AIJob.objects.exists())


@override_settings(MEDIA_ROOT=MEDIA_ROOT, AI_JOBS_RUN_INLINE=False)
class BackgroundJobThreadTests(TransactionTestCase):
    """
    Jobs on real worker threads: the request answers before the AI
    service does, and polling shows the work as it progresses.
    """

    setUp = AttendanceFlowTests.setUp
    register = AttendanceFlowTests.register
    poll = AttendanceFlowTests.poll

    def wait_for(self, job_id, timeout=10):
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            job = self.poll(job_id).data["data"]

            if job["done"]:
                return job

            time.sleep(0.05)

        self.fail(f"Job {job_id} did not finish in {timeout}s")

    def test_bulk_registration_answers_before_the_ai_finishes(self):
        release = threading.Event()

        def slow_register(**kwargs):
            release.wait(5)
            return {"status": "success"}

        self.ai.register_face.side_effect = slow_register

        response = self.client.post(
            reverse("attendance_student:face-register"),
            {"images": [image_file("STU1.jpg"), image_file("STU2.jpg")]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)
        job = response.data["data"]
        self.assertFalse(job["done"])
        self.assertIn(job["status"], (AIJobStatus.PENDING, AIJobStatus.RUNNING))
        self.assertEqual(job["poll_after"], 2)
        self.assertFalse(FaceRegistration.objects.exists())

        release.set()
        job = self.wait_for(job["id"])

        self.assertEqual(job["status"], AIJobStatus.SUCCEEDED, job)
        self.assertEqual(job["result"]["registered"], 2)
        self.assertEqual((job["processed"], job["succeeded"]), (2, 2))
        self.assertEqual(FaceRegistration.objects.count(), 2)
        self.s1.refresh_from_db()
        self.assertTrue(self.s1.has_profile_image)

    def test_verification_runs_in_the_background(self):
        self.register(self.s1, self.s2)
        self.ai.verify_attendance.return_value = {
            "image_count": 1,
            "detected_faces": 1,
            "matches": [{"student_id": "STU1", "similarity": 0.9}],
            "students": [{"student_id": "STU1", "status": "Present"}],
        }

        response = self.client.post(
            reverse("attendance_student:attendance-verify"),
            {"images": [image_file()]},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202, response.data)
        job = self.wait_for(response.data["data"]["id"])

        self.assertEqual(job["status"], AIJobStatus.SUCCEEDED, job)
        session = AttendanceSession.objects.get(pk=job["result"]["session"])
        self.assertEqual(
            session.records.get(student=self.s1).status, "PRESENT",
        )
