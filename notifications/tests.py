import shutil
import tempfile
import threading
from unittest import mock
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, ClassSection, SchoolClass, Section
from accounts.models import User
from common.choices import UserRole
from parents.models import Parent
from schools.models import School
from students.models import Student
from teachers.models import Teacher

from .models import Notification, NotificationRecipient, PushSubscription

MEDIA_ROOT = tempfile.mkdtemp()


def make_user(email, role):
    user = User(email=email, name=email.split("@")[0], role=role)
    user.set_password("x")
    user.save()
    return user


def make_school(code, admin):
    return School.objects.create(
        name=f"School {code}", code=code, email=f"{code}@x.com", phone="9999999999",
        address="a", city="c", state="s", country="in", pincode="1", admin=admin,
    )


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class NotificationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.super_admin = make_user("super@x.com", UserRole.SUPER_ADMIN)
        self.admin_a = make_user("admin-a@x.com", UserRole.SCHOOL_ADMIN)
        self.admin_b = make_user("admin-b@x.com", UserRole.SCHOOL_ADMIN)
        self.school_a = make_school("A", self.admin_a)
        self.school_b = make_school("B", self.admin_b)

        self.section_a1 = self.section(self.school_a, "1")
        self.section_a2 = self.section(self.school_a, "2")
        self.section_b1 = self.section(self.school_b, "1")

        self.teacher_a1 = self.teacher("ta1@x.com", self.school_a, self.section_a1)
        self.teacher_a2 = self.teacher("ta2@x.com", self.school_a, self.section_a2)
        self.teacher_b1 = self.teacher("tb1@x.com", self.school_b, self.section_b1)

        self.parent_a1 = self.parent("9000000001", self.section_a1, "S1")
        self.parent_a2 = self.parent("9000000002", self.section_a2, "S2")
        self.parent_b1 = self.parent("9000000003", self.section_b1, "S3")

    def section(self, school, name):
        today = timezone.localdate()
        year, _ = AcademicYear.objects.get_or_create(
            school=school, name="Y",
            defaults={
                "is_active": True,
                "start_date": today - timedelta(days=10),
                "end_date": today + timedelta(days=10),
            },
        )
        school_class, _ = SchoolClass.objects.get_or_create(school=school, name="5")
        return ClassSection.objects.create(
            academic_year=year, school_class=school_class,
            section=Section.objects.create(school=school, name=name),
        )

    def teacher(self, email, school, section):
        user = make_user(email, UserRole.TEACHER)
        Teacher.objects.create(
            user=user, school=school, employee_id=email[:3], class_section=section,
        )
        return user

    def parent(self, phone, section, student_id):
        student = Student.objects.create(
            school=section.academic_year.school, class_section=section,
            name=f"Kid {student_id}", student_id=student_id, roll_number="1",
        )
        user = User(name=f"Parent {phone}", phone_number=phone, role=UserRole.PARENT)
        user.set_password("x")
        user.save()
        Parent.objects.create(user=user).students.add(student)
        user.student = student
        return user

    def send(self, sender, data, files=None):
        client = APIClient()
        client.force_authenticate(sender)
        payload = {"title": "Hello", "message": "Body", **data}

        if files:
            payload["attachments"] = files

        return client.post(
            reverse("notifications:notification-list-create"), payload, format="multipart",
        )

    def recipients(self):
        return set(NotificationRecipient.objects.values_list("user_id", flat=True))

    def test_super_admin_to_school_admins_everywhere_with_attachments(self):
        files = [
            SimpleUploadedFile("circular.pdf", b"%PDF-1.4 data", content_type="application/pdf"),
            SimpleUploadedFile("clip.mp4", b"video-bytes", content_type="video/mp4"),
            SimpleUploadedFile("pic.png", b"png-bytes", content_type="image/png"),
        ]

        response = self.send(self.super_admin, {"to_school_admins": True}, files)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.recipients(), {self.admin_a.pk, self.admin_b.pk})
        kinds = [a["kind"] for a in response.data["data"]["attachments"]]
        self.assertEqual(kinds, ["PDF", "VIDEO", "IMAGE"])

    def test_super_admin_narrows_by_school(self):
        response = self.send(
            self.super_admin,
            {"to_teachers": True, "to_parents": True, "schools": [self.school_b.pk]},
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.recipients(), {self.teacher_b1.pk, self.parent_b1.pk})

    def test_school_admin_audience_is_own_school(self):
        response = self.send(self.admin_a, {"to_teachers": True, "to_parents": True})

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            self.recipients(),
            {self.teacher_a1.pk, self.teacher_a2.pk, self.parent_a1.pk, self.parent_a2.pk},
        )

    def test_school_admin_by_class_section(self):
        response = self.send(
            self.admin_a, {"to_parents": True, "class_sections": [self.section_a2.pk]},
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.recipients(), {self.parent_a2.pk})

        other_school = self.send(
            self.admin_a, {"to_parents": True, "class_sections": [self.section_b1.pk]},
        )
        self.assertEqual(other_school.status_code, 400)

    def test_school_admin_cannot_message_school_admins(self):
        response = self.send(self.admin_a, {"to_school_admins": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("to_school_admins", response.data["errors"])

    def test_teacher_reaches_only_own_section_parents(self):
        response = self.send(self.teacher_a1, {"to_parents": True})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.recipients(), {self.parent_a1.pk})

        self.assertEqual(self.send(self.teacher_a1, {"to_teachers": True}).status_code, 400)

    def test_individual_recipients(self):
        response = self.send(
            self.admin_a, {"users": [self.teacher_a2.pk, self.parent_a1.pk]},
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.recipients(), {self.teacher_a2.pk, self.parent_a1.pk})

        outside = self.send(self.admin_a, {"users": [self.teacher_b1.pk]})
        self.assertEqual(outside.status_code, 400)

        teacher_to_teacher = self.send(self.teacher_a1, {"users": [self.teacher_a2.pk]})
        self.assertEqual(teacher_to_teacher.status_code, 400)

    def test_teacher_to_parents_of_one_student(self):
        response = self.send(
            self.teacher_a1, {"students": [self.parent_a1.student.pk]},
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.recipients(), {self.parent_a1.pk})

        other_section = self.send(
            self.teacher_a1, {"students": [self.parent_a2.student.pk]},
        )
        self.assertEqual(other_section.status_code, 400)

    def test_requires_audience_and_content_and_blocks_scripts(self):
        self.assertEqual(self.send(self.admin_a, {}).status_code, 400)
        self.assertEqual(
            self.send(self.admin_a, {"to_parents": True, "message": ""}).status_code, 400,
        )
        evil = SimpleUploadedFile("x.html", b"<script>", content_type="text/html")
        self.assertEqual(
            self.send(self.admin_a, {"to_parents": True}, [evil]).status_code, 400,
        )
        self.assertFalse(Notification.objects.exists())

    def test_inbox_read_flow_and_parent_access(self):
        self.send(self.teacher_a1, {"to_parents": True, "title": "Trip"})
        notification = Notification.objects.get()

        parent = APIClient()
        parent.force_authenticate(self.parent_a1)

        inbox = parent.get(reverse("notifications:inbox"))
        self.assertEqual(inbox.status_code, 200)
        item = inbox.data["data"]["results"][0]
        self.assertEqual(item["title"], "Trip")
        self.assertFalse(item["is_read"])
        self.assertEqual(
            parent.get(reverse("notifications:inbox-unread-count")).data["data"]["unread"], 1,
        )

        parent.get(reverse("notifications:inbox-detail", args=[notification.pk]))
        self.assertEqual(
            parent.get(reverse("notifications:inbox-unread-count")).data["data"]["unread"], 0,
        )

        sender = APIClient()
        sender.force_authenticate(self.teacher_a1)
        sent = sender.get(reverse("notifications:notification-list-create"))
        self.assertEqual(sent.data["data"]["results"][0]["read_count"], 1)
        self.assertEqual(self.send(self.parent_a1, {"users": [self.teacher_a1.pk]}).status_code, 403)

        other = APIClient()
        other.force_authenticate(self.parent_a2)
        self.assertEqual(
            other.get(reverse("notifications:inbox-detail", args=[notification.pk])).status_code,
            404,
        )

    def test_school_admin_can_withdraw_teacher_notification(self):
        self.send(self.teacher_a1, {"to_parents": True})
        notification = Notification.objects.get()

        other_admin = APIClient()
        other_admin.force_authenticate(self.admin_b)
        self.assertEqual(
            other_admin.delete(
                reverse("notifications:notification-detail", args=[notification.pk]),
            ).status_code,
            404,
        )

        admin = APIClient()
        admin.force_authenticate(self.admin_a)
        response = admin.delete(
            reverse("notifications:notification-detail", args=[notification.pk]),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(NotificationRecipient.objects.exists())

    def test_sender_sees_who_saw_it_and_when(self):
        """Read times are pinned apart, since the OS clock can tie two quick reads; seen rows come first, latest first."""
        self.send(self.admin_a, {"to_teachers": True, "to_parents": True})
        notification = Notification.objects.get()

        for minutes, user in ((1, self.parent_a1), (2, self.teacher_a2)):
            client = APIClient()
            client.force_authenticate(user)
            client.get(reverse("notifications:inbox-detail", args=[notification.pk]))
            NotificationRecipient.objects.filter(user=user).update(
                read_at=timezone.now() + timedelta(minutes=minutes),
            )

        admin = APIClient()
        admin.force_authenticate(self.admin_a)

        detail = admin.get(
            reverse("notifications:notification-detail", args=[notification.pk]),
        ).data["data"]
        self.assertEqual(detail["recipient_count"], 4)
        self.assertEqual(detail["read_count"], 2)
        self.assertEqual(detail["unread_count"], 2)
        self.assertIsNotNone(detail["last_read_at"])
        self.assertEqual(
            detail["read_summary"],
            [
                {"role": "PARENT", "total": 2, "seen": 1, "not_seen": 1},
                {"role": "TEACHER", "total": 2, "seen": 1, "not_seen": 1},
            ],
        )

        url = reverse("notifications:notification-recipients", args=[notification.pk])
        rows = admin.get(url).data["data"]["results"]
        self.assertEqual(
            [r["user"]["id"] for r in rows[:2]],
            [self.teacher_a2.pk, self.parent_a1.pk],
        )
        self.assertTrue(all(r["read_at"] for r in rows[:2]))
        self.assertTrue(all(r["read_at"] is None for r in rows[2:]))

        seen_parents = admin.get(url, {"is_read": "true", "role": "parent"}).data["data"]
        self.assertEqual(
            [r["user"]["id"] for r in seen_parents["results"]], [self.parent_a1.pk],
        )

    def test_push_subscription_moves_between_users_and_unsubscribes(self):
        """When someone else signs in on the same device the endpoint moves to them; only the owner can remove it."""
        sub = {
            "endpoint": "https://push.example.com/send/abc",
            "keys": {"p256dh": "BPkey", "auth": "authsecret"},
        }
        teacher = APIClient()
        teacher.force_authenticate(self.teacher_a1)
        response = teacher.post(reverse("notifications:push-subscribe"), sub, format="json")
        self.assertEqual(response.status_code, 201, response.data)

        parent = APIClient()
        parent.force_authenticate(self.parent_a1)
        parent.post(reverse("notifications:push-subscribe"), sub, format="json")
        self.assertEqual(list(PushSubscription.objects.values_list("user_id", flat=True)), [self.parent_a1.pk])

        teacher.post(reverse("notifications:push-unsubscribe"), {"endpoint": sub["endpoint"]}, format="json")
        self.assertEqual(PushSubscription.objects.count(), 1)
        parent.post(reverse("notifications:push-unsubscribe"), {"endpoint": sub["endpoint"]}, format="json")
        self.assertEqual(PushSubscription.objects.count(), 0)

    @override_settings(VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv")
    def test_sending_pushes_to_every_recipient_after_commit(self):
        """Delivery runs on a thread, so the test waits for it before checking."""
        with mock.patch("notifications.push._deliver") as deliver, self.captureOnCommitCallbacks(execute=True):
            response = self.send(self.teacher_a1, {"to_parents": True})

        self.assertEqual(response.status_code, 201, response.data)
        for thread in threading.enumerate():
            if thread is not threading.current_thread() and thread.daemon:
                thread.join(timeout=2)
        user_ids, payload = deliver.call_args.args
        self.assertEqual(set(user_ids), {self.parent_a1.pk})
        self.assertEqual(payload["path"], "inbox")
        self.assertEqual(payload["title"], "Hello")

    def test_push_public_key_is_null_when_not_configured(self):
        client = APIClient()
        client.force_authenticate(self.parent_a1)
        with override_settings(VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY=""):
            response = client.get(reverse("notifications:push-public-key"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["public_key"])
