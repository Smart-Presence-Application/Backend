import io
import os
import shutil
import tempfile
from datetime import datetime, time, timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import User
from common.choices import UserRole
from schools.models import School
from teachers.models import Teacher

from .models import (
    TeacherAttendance,
    TeacherAttendanceSettings,
    TeacherAttendanceStatus,
    WorkDayType,
)

MEDIA_ROOT = tempfile.mkdtemp()


def camera_photo(exif_taken_at=None):
    """A distinct JPEG each call, so duplicate-image checks don't trip."""

    buffer = io.BytesIO()
    image = Image.frombytes("RGB", (16, 16), os.urandom(16 * 16 * 3))
    kwargs = {}

    if exif_taken_at is not None:
        exif = Image.Exif()
        exif[306] = exif_taken_at.strftime("%Y:%m:%d %H:%M:%S")
        kwargs["exif"] = exif

    image.save(buffer, format="JPEG", **kwargs)
    return SimpleUploadedFile("cam.jpg", buffer.getvalue(), content_type="image/jpeg")


def make_user(email, role):
    user = User(email=email, name=email.split("@")[0], role=role)
    user.set_password("x")
    user.save()
    return user


def at(hour, minute=0):
    return timezone.make_aware(
        datetime.combine(timezone.localdate(), time(hour, minute)),
    )


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TeacherAttendanceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.school_admin = make_user("admin@x.com", UserRole.SCHOOL_ADMIN)
        self.school = School.objects.create(
            name="School", code="SCH", email="s@x.com", phone="9999999999",
            address="a", city="c", state="s", country="in", pincode="1",
            admin=self.school_admin,
        )
        self.teacher_user = make_user("t@x.com", UserRole.TEACHER)
        self.teacher = Teacher.objects.create(
            user=self.teacher_user, school=self.school, employee_id="E1",
        )
        self.other_user = make_user("t2@x.com", UserRole.TEACHER)
        self.other_teacher = Teacher.objects.create(
            user=self.other_user, school=self.school, employee_id="E2",
        )

        self.client = APIClient()
        self.client.force_authenticate(self.teacher_user)
        self.admin = APIClient()
        self.admin.force_authenticate(self.school_admin)

    def capture(self, kind, now, captured_at=None, image=None, client=None, offline=False):
        with mock.patch("django.utils.timezone.now", return_value=now):
            return (client or self.client).post(
                reverse(f"attendance_teacher:{kind}"),
                {
                    "image": image or camera_photo(),
                    "captured_at": (captured_at or now).isoformat(),
                    "offline": "true" if offline else "false",
                },
                format="multipart",
            )

    def test_offline_capture_keeps_device_time_and_is_flagged(self):
        """Photos taken at 9:00 and 15:00 with no internet, synced at 16:00."""
        synced = at(16, 0)
        check_in = self.capture("check-in", synced, captured_at=at(9, 0), offline=True)
        self.assertEqual(check_in.status_code, 201, check_in.data)
        self.assertTrue(check_in.data["data"]["check_in_offline"])

        check_out = self.capture("check-out", synced, captured_at=at(15, 0), offline=True)
        self.assertEqual(check_out.status_code, 201, check_out.data)

        attendance = TeacherAttendance.objects.get()
        self.assertEqual(attendance.check_in_captured_at, at(9, 0))
        self.assertEqual(attendance.check_out_captured_at, at(15, 0))
        self.assertTrue(attendance.check_in_offline)
        self.assertTrue(attendance.check_out_offline)

    def test_offline_capture_limits(self):
        """Offline photos must be recent and match their EXIF time; online, a 2-hour-old photo is refused."""
        now = at(23, 0)
        too_old = self.capture("check-in", now, captured_at=now - timedelta(hours=13), offline=True)
        self.assertEqual(too_old.status_code, 400)
        self.assertIn("captured_at", too_old.data["errors"])

        future = self.capture("check-in", now, captured_at=now + timedelta(hours=1), offline=True)
        self.assertEqual(future.status_code, 400)

        mismatch = self.capture(
            "check-in", now, captured_at=at(13, 0), offline=True,
            image=camera_photo(exif_taken_at=at(13, 0) - timedelta(days=2)),
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("image", mismatch.data["errors"])

        online = self.capture("check-in", now, captured_at=now - timedelta(hours=2))
        self.assertEqual(online.status_code, 400)

    def test_check_in_records_server_time_as_draft(self):
        """The device clock is 30s off; the server time is what gets stored."""
        now = at(9, 0)
        response = self.capture("check-in", now, captured_at=now - timedelta(seconds=30))

        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        self.assertEqual(data["status"], TeacherAttendanceStatus.DRAFT)
        attendance = TeacherAttendance.objects.get()
        self.assertEqual(attendance.check_in_captured_at, now)
        self.assertTrue(attendance.check_in_image)

        again = self.capture("check-in", at(9, 5))
        self.assertEqual(again.status_code, 400)

    def test_stale_photo_is_rejected(self):
        now = at(9, 0)

        old_timestamp = self.capture("check-in", now, captured_at=now - timedelta(hours=2))
        self.assertEqual(old_timestamp.status_code, 400)
        self.assertIn("captured_at", old_timestamp.data["errors"])

        old_exif = self.capture(
            "check-in", now, image=camera_photo(exif_taken_at=now - timedelta(days=3)),
        )
        self.assertEqual(old_exif.status_code, 400)
        self.assertIn("image", old_exif.data["errors"])

        fresh_exif = self.capture("check-in", now, image=camera_photo(exif_taken_at=now))
        self.assertEqual(fresh_exif.status_code, 201, fresh_exif.data)

    def test_same_photo_cannot_be_reused(self):
        photo = camera_photo()
        self.capture("check-in", at(9), image=photo)

        photo.seek(0)
        reused = SimpleUploadedFile("again.jpg", photo.read(), content_type="image/jpeg")
        response = self.capture("check-out", at(15), image=reused)

        self.assertEqual(response.status_code, 400)
        self.assertIn("image", response.data["errors"])

    def test_check_out_requires_check_in(self):
        response = self.capture("check-out", at(15))
        self.assertEqual(response.status_code, 400)

    def test_only_teachers_capture(self):
        response = self.capture("check-in", at(9), client=self.admin)
        self.assertEqual(response.status_code, 403)

    def test_full_flow_draft_then_verify_with_increased_time(self):
        """
        2.5h would be ABSENT under the default 3h half-day, so the admin
        extends the exit; the captured time is kept alongside the verified one.
        """
        self.capture("check-in", at(9, 0))
        response = self.capture("check-out", at(11, 30))
        self.assertEqual(response.status_code, 201, response.data)
        attendance_id = response.data["data"]["id"]

        for client in (self.client, self.admin):
            draft = client.get(
                reverse("attendance_teacher:record-detail", args=[attendance_id]),
            ).data["data"]
            self.assertEqual(draft["status"], TeacherAttendanceStatus.DRAFT)
            self.assertEqual(draft["worked_minutes"], 150)
            self.assertIsNone(draft["day_type"])

        verify_url = reverse("attendance_teacher:record-verify", args=[attendance_id])
        self.assertEqual(self.client.post(verify_url, {}, format="json").status_code, 403)

        response = self.admin.post(
            verify_url,
            {"check_out_time": "13:00", "remarks": "Exam duty"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["status"], TeacherAttendanceStatus.VERIFIED)
        self.assertEqual(data["worked_minutes"], 240)
        self.assertEqual(data["worked_hours"], 4.0)
        self.assertEqual(data["day_type"], WorkDayType.HALF_DAY)

        mine = self.client.get(
            reverse("attendance_teacher:record-detail", args=[attendance_id]),
        ).data["data"]
        self.assertEqual(
            datetime.fromisoformat(mine["check_out_captured_at"]), at(11, 30),
        )
        self.assertEqual(datetime.fromisoformat(mine["check_out_at"]), at(13, 0))

    def test_admin_can_mark_half_day_and_must_supply_missing_checkout(self):
        """Once verified before the teacher checked out, check-out is closed."""
        response = self.capture("check-in", at(9))
        attendance_id = response.data["data"]["id"]
        verify_url = reverse("attendance_teacher:record-verify", args=[attendance_id])

        self.assertEqual(self.admin.post(verify_url, {}, format="json").status_code, 400)
        self.assertEqual(
            self.admin.post(
                verify_url, {"check_out_time": "08:00"}, format="json",
            ).status_code,
            400,
        )

        response = self.admin.post(
            verify_url,
            {"check_out_time": "17:00", "day_type": WorkDayType.HALF_DAY},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["day_type"], WorkDayType.HALF_DAY)
        self.assertTrue(response.data["data"]["day_type_overridden"])

        self.assertEqual(self.capture("check-out", at(17, 5)).status_code, 400)

    def test_settings(self):
        url = reverse("attendance_teacher:settings")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["full_day_minutes"], 360)

        self.assertEqual(
            self.client.patch(url, {"half_day_minutes": 200}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.admin.patch(url, {"half_day_minutes": 400}, format="json").status_code,
            400,
        )

        response = self.admin.patch(
            url, {"full_day_minutes": 420, "half_day_minutes": 210}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["half_day_hours"], 3.5)
        self.assertEqual(
            TeacherAttendanceSettings.objects.get(school=self.school).full_day_minutes,
            420,
        )

    def _verified(self, teacher, days_ago, minutes, day_type):
        day = timezone.localdate() - timedelta(days=days_ago)
        start = timezone.make_aware(datetime.combine(day, time(9)))
        return TeacherAttendance.objects.create(
            teacher=teacher,
            school=self.school,
            date=day,
            status=TeacherAttendanceStatus.VERIFIED,
            check_in_captured_at=start,
            check_out_captured_at=start + timedelta(minutes=minutes),
            check_in_image_hash=f"h{teacher.pk}-{days_ago}",
            worked_minutes=minutes,
            day_type=day_type,
        )

    def test_summary(self):
        self._verified(self.teacher, 1, 400, WorkDayType.FULL_DAY)
        self._verified(self.teacher, 2, 200, WorkDayType.HALF_DAY)
        self._verified(self.teacher, 3, 190, WorkDayType.HALF_DAY)
        self._verified(self.teacher, 4, 60, WorkDayType.ABSENT)
        self._verified(self.teacher, 40, 400, WorkDayType.FULL_DAY)
        self._verified(self.other_teacher, 1, 400, WorkDayType.FULL_DAY)
        self.capture("check-in", at(9))

        url = reverse("attendance_teacher:summary")
        date_from = (timezone.localdate() - timedelta(days=30)).isoformat()

        mine = self.client.get(url, {"date_from": date_from}).data["data"]["teachers"]
        self.assertEqual(len(mine), 1)
        row = mine[0]
        self.assertEqual(row["total_working_minutes"], 850)
        self.assertEqual(row["total_working_hours"], 14.17)
        self.assertEqual(row["total_full_days"], 1)
        self.assertEqual(row["total_half_days"], 2)
        self.assertEqual(row["total_absent_days"], 1)
        self.assertEqual(row["total_working_days"], 2.0)
        self.assertEqual(row["pending_verification"], 1)

        school_rows = self.admin.get(url, {"date_from": date_from}).data["data"]["teachers"]
        self.assertEqual([r["employee_id"] for r in school_rows], ["E1", "E2"])

    def test_teachers_only_see_their_own_records(self):
        record = self._verified(self.other_teacher, 1, 400, WorkDayType.FULL_DAY)

        response = self.client.get(
            reverse("attendance_teacher:record-detail", args=[record.pk]),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            self.admin.get(reverse("attendance_teacher:record-list")).data["data"]["count"],
            1,
        )

    def test_only_admins_can_delete_attendance(self):
        self.capture("check-in", at(9, 0))
        self.capture("check-out", at(16, 0))
        attendance = TeacherAttendance.objects.get()
        images = [attendance.check_in_image.path, attendance.check_out_image.path]
        url = reverse("attendance_teacher:record-detail", args=[attendance.pk])

        self.assertEqual(self.client.delete(url).status_code, 403)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.admin.delete(url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(TeacherAttendance.objects.exists())
        self.assertFalse(any(os.path.exists(path) for path in images))
        self.assertEqual(self.admin.delete(url).status_code, 404)
