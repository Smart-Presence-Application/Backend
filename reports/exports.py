"""
Report definitions: what each report contains and who may download it.

Every report starts from the same scoped querysets the rest of the API
uses (students.selectors, teachers.selectors, ...), so a download can
never show more than the actor already sees on screen. Filters only
narrow that scope further; the ``*_LOOKUPS`` maps tie each filter a
report understands to a lookup on its queryset.

``my-attendance`` is the same report School Admins get, which for a
teacher holds only their own days. ``ALL_KEY`` bundles every report the
actor may download into one workbook.
"""

from dataclasses import dataclass
from typing import Callable

from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch, Q, QuerySet

from attendance_student.models import AttendanceRecord
from attendance_student.selectors import get_sessions_visible_to
from attendance_teacher.models import WorkDayType
from attendance_teacher.selectors import get_attendance_visible_to
from common.choices import AttendanceStatus, UserRole
from common.ordering import roll_order
from parents.models import Parent
from schools.models import School
from students.selectors import get_students_visible_to, is_school_admin, is_super_admin
from system.models import ActivityLog
from teachers.selectors import get_teachers_visible_to

from .excel import Sheet

User = get_user_model()

SUPER = (UserRole.SUPER_ADMIN,)
ADMINS = (UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN)
STAFF = (UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER)
TEACHER_ONLY = (UserRole.TEACHER,)


def role_of(actor) -> str | None:
    if is_super_admin(actor):
        return UserRole.SUPER_ADMIN

    return getattr(actor, "role", None)


def narrow(queryset: QuerySet, params: dict, lookups: dict[str, str]) -> QuerySet:
    """
    Apply each given filter through its lookup on this queryset.
    Filters a report does not support are ignored.
    """

    conditions = {
        lookups[name]: value
        for name, value in params.items()
        if name in lookups and value not in (None, "")
    }

    return queryset.filter(**conditions)


def class_cells(class_section) -> list:
    if class_section is None:
        return ["", "", ""]

    return [
        class_section.academic_year.name,
        class_section.school_class.name,
        class_section.section.name,
    ]


def hours(minutes: int | None) -> str:
    if minutes is None:
        return ""

    return f"{minutes // 60}:{minutes % 60:02d}"


def percent(part: int, whole: int):
    return round(part * 100 / whole, 1) if whole else ""


STUDENT_LOOKUPS = {
    "school": "school_id",
    "academic_year": "class_section__academic_year_id",
    "class_section": "class_section_id",
    "school_class": "class_section__school_class_id",
    "section": "class_section__section_id",
    "student": "pk",
}

STUDENT_ATTENDANCE_LOOKUPS = {
    "school": "session__school_id",
    "academic_year": "session__class_section__academic_year_id",
    "class_section": "session__class_section_id",
    "school_class": "session__class_section__school_class_id",
    "section": "session__class_section__section_id",
    "student": "student_id",
    "date_from": "session__date__gte",
    "date_to": "session__date__lte",
    "status": "status",
    "session_status": "session__status",
}

TEACHER_LOOKUPS = {
    "school": "school_id",
    "academic_year": "class_section__academic_year_id",
    "class_section": "class_section_id",
    "school_class": "class_section__school_class_id",
    "section": "class_section__section_id",
    "teacher": "pk",
    "is_active": "user__is_active",
}

TEACHER_ATTENDANCE_LOOKUPS = {
    "school": "school_id",
    "teacher": "teacher_id",
    "date_from": "date__gte",
    "date_to": "date__lte",
    "verification": "status",
    "day_type": "day_type",
}

SCHOOL_LOOKUPS = {
    "school": "pk",
    "school_status": "status",
}

USER_LOOKUPS = {
    "role": "role",
    "is_active": "is_active",
}


def students_scope(actor, params) -> QuerySet:
    return narrow(get_students_visible_to(actor), params, STUDENT_LOOKUPS)


def students_sheets(actor, params) -> list[Sheet]:
    students = students_scope(actor, params).prefetch_related(
        Prefetch("parents", queryset=Parent.objects.select_related("user"))
    )

    sheet = Sheet(
        "Students",
        [
            "School", "Academic year", "Class", "Section", "Roll no.",
            "Student ID", "Name", "Has photo", "Face registered",
            "Parent name(s)", "Parent mobile(s)", "Enrolled on",
        ],
    )

    for student in students:
        parents = list(student.parents.all())
        sheet.rows.append(
            [
                student.school.name,
                *class_cells(student.class_section),
                student.roll_number,
                student.student_id,
                student.name,
                student.has_profile_image,
                hasattr(student, "face_registration"),
                ", ".join(p.user.name for p in parents),
                ", ".join(p.user.phone_number or "" for p in parents),
                student.created_at,
            ]
        )

    return [sheet]


def parents_sheets(actor, params) -> list[Sheet]:
    """
    One row per parent and child, in the children's roll-number order,
    so a parent of two children appears twice.
    """

    students = students_scope(actor, params).prefetch_related(
        Prefetch("parents", queryset=Parent.objects.select_related("user").order_by("user__name"))
    )

    sheet = Sheet(
        "Parents",
        [
            "Parent name", "Mobile", "Email", "Account active",
            "Changed own password", "School", "Academic year", "Class",
            "Section", "Roll no.", "Student ID", "Student name", "Added on",
        ],
    )

    for student in students:
        for parent in student.parents.all():
            sheet.rows.append(
                [
                    parent.user.name,
                    parent.user.phone_number,
                    parent.user.email,
                    parent.user.is_active,
                    parent.password_changed,
                    student.school.name,
                    *class_cells(student.class_section),
                    student.roll_number,
                    student.student_id,
                    student.name,
                    parent.created_at,
                ]
            )

    return [sheet]


def student_attendance_sheets(actor, params) -> list[Sheet]:
    """
    A per-record detail sheet and a per-student summary, both in natural
    roll order within each class.
    """

    records = narrow(
        AttendanceRecord.objects.filter(session__in=get_sessions_visible_to(actor)),
        params,
        STUDENT_ATTENDANCE_LOOKUPS,
    ).select_related(
        "student",
        "updated_by",
        "session__school",
        "session__locked_by",
        "session__class_section__academic_year",
        "session__class_section__school_class",
        "session__class_section__section",
    ).order_by(
        "session__date",
        "session__class_section__school_class__name",
        "session__class_section__section__name",
        roll_order("student__roll_number"),
    )

    detail = Sheet(
        "Attendance",
        [
            "Date", "School", "Academic year", "Class", "Section", "Roll no.",
            "Student ID", "Name", "Status", "Marked by", "AI result",
            "AI similarity", "Remarks", "Attendance state", "Locked by",
            "Locked at", "Last changed by",
        ],
    )

    totals: dict[int, list] = {}

    for record in records:
        session = record.session
        student = record.student
        classes = class_cells(session.class_section)

        detail.rows.append(
            [
                session.date,
                session.school.name,
                *classes,
                student.roll_number,
                student.student_id,
                student.name,
                record.get_status_display(),
                record.get_source_display(),
                record.get_ai_status_display() if record.ai_status else "",
                round(record.similarity, 3) if record.similarity is not None else "",
                record.remarks,
                session.get_status_display(),
                session.locked_by.name if session.locked_by else "",
                session.locked_at,
                record.updated_by.name if record.updated_by else "",
            ]
        )

        row = totals.setdefault(
            student.pk,
            [session.school.name, *classes, student.roll_number, student.student_id, student.name, 0, 0],
        )
        row[-2 if record.status == AttendanceStatus.PRESENT else -1] += 1

    summary = Sheet(
        "Summary",
        [
            "School", "Academic year", "Class", "Section", "Roll no.",
            "Student ID", "Name", "Days recorded", "Present", "Absent",
            "Attendance %",
        ],
    )

    for row in totals.values():
        present, absent = row[-2], row[-1]
        summary.rows.append([*row[:-2], present + absent, present, absent, percent(present, present + absent)])

    summary.rows.sort(key=lambda r: (r[0], r[1], r[2], r[3], r[4].zfill(20)))

    return [summary, detail]


def teachers_sheets(actor, params) -> list[Sheet]:
    teachers = narrow(get_teachers_visible_to(actor), params, TEACHER_LOOKUPS).order_by(
        "school__name",
        "employee_id",
    )

    sheet = Sheet(
        "Teachers",
        [
            "School", "Employee ID", "Name", "Email", "Mobile", "Gender",
            "Academic year", "Class", "Section", "Joining date", "Address",
            "City", "State", "Country", "Pincode", "Account active", "Added on",
        ],
    )

    for teacher in teachers:
        user = teacher.user
        sheet.rows.append(
            [
                teacher.school.name,
                teacher.employee_id,
                user.name,
                user.email,
                user.phone_number,
                user.get_gender_display() if user.gender else "",
                *class_cells(teacher.class_section),
                teacher.joining_date,
                teacher.address,
                teacher.city,
                teacher.state,
                teacher.country,
                teacher.pincode,
                user.is_active,
                teacher.created_at,
            ]
        )

    return [sheet]


def teacher_attendance_sheets(actor, params) -> list[Sheet]:
    attendances = narrow(
        get_attendance_visible_to(actor),
        params,
        TEACHER_ATTENDANCE_LOOKUPS,
    ).order_by("date", "school__name", "teacher__employee_id")

    detail = Sheet(
        "Attendance",
        [
            "Date", "School", "Employee ID", "Name", "Check in", "Check out",
            "Hours worked", "Day type", "Day type set by admin",
            "Checked in offline", "Checked out offline", "Status",
            "Verified by", "Verified at", "Remarks",
        ],
    )

    totals: dict[int, dict] = {}

    for attendance in attendances:
        teacher = attendance.teacher
        worked = attendance.worked_minutes

        if worked is None:
            worked = attendance.current_worked_minutes

        detail.rows.append(
            [
                attendance.date,
                attendance.school.name,
                teacher.employee_id,
                teacher.user.name,
                attendance.check_in_at,
                attendance.check_out_at,
                hours(worked),
                attendance.get_day_type_display() if attendance.day_type else "",
                attendance.day_type_overridden,
                attendance.check_in_offline,
                attendance.check_out_offline,
                attendance.get_status_display(),
                attendance.verified_by.name if attendance.verified_by else "",
                attendance.verified_at,
                attendance.remarks,
            ]
        )

        total = totals.setdefault(
            teacher.pk,
            {
                "head": [attendance.school.name, teacher.employee_id, teacher.user.name],
                "days": 0,
                "verified": 0,
                "minutes": 0,
                **{day_type: 0 for day_type in WorkDayType.values},
            },
        )
        total["days"] += 1
        total["verified"] += attendance.is_verified
        total["minutes"] += worked or 0

        if attendance.day_type:
            total[attendance.day_type] += 1

    summary = Sheet(
        "Summary",
        [
            "School", "Employee ID", "Name", "Days recorded", "Verified",
            "Full days", "Half days", "Absent", "Total hours worked",
        ],
    )

    for total in sorted(totals.values(), key=lambda t: t["head"]):
        summary.rows.append(
            [
                *total["head"],
                total["days"],
                total["verified"],
                total[WorkDayType.FULL_DAY],
                total[WorkDayType.HALF_DAY],
                total[WorkDayType.ABSENT],
                hours(total["minutes"]),
            ]
        )

    return [summary, detail]


def schools_sheets(actor, params) -> list[Sheet]:
    schools = narrow(
        School.objects.select_related("admin").annotate(
            teacher_count=Count("teachers", distinct=True),
            student_count=Count("students", distinct=True),
        ),
        params,
        SCHOOL_LOOKUPS,
    ).order_by("name")

    sheet = Sheet(
        "Schools",
        [
            "Name", "Code", "Status", "Email", "Phone", "Address", "City",
            "State", "Country", "Pincode", "Admin name", "Admin email",
            "Attendance threshold %", "Teachers", "Students", "Created on",
        ],
    )

    for school in schools:
        sheet.rows.append(
            [
                school.name,
                school.code,
                school.get_status_display(),
                school.email,
                school.phone,
                school.address,
                school.city,
                school.state,
                school.country,
                school.pincode,
                school.admin.name,
                school.admin.email,
                school.attendance_threshold,
                school.teacher_count,
                school.student_count,
                school.created_at,
            ]
        )

    return [sheet]


def users_sheets(actor, params) -> list[Sheet]:
    users = narrow(
        User.objects.select_related("managed_school", "teacher_profile__school"),
        params,
        USER_LOOKUPS,
    ).order_by("role", "name")

    school = params.get("school")

    if school:
        users = users.filter(Q(managed_school=school) | Q(teacher_profile__school=school) | Q(parent_profile__students__school=school)).distinct()

    sheet = Sheet(
        "Users",
        ["Name", "Role", "Email", "Mobile", "Gender", "School", "Active", "Joined on"],
    )

    for user in users:
        managed = getattr(user, "managed_school", None)
        teacher = getattr(user, "teacher_profile", None)
        school_name = managed.name if managed else teacher.school.name if teacher else ""

        sheet.rows.append(
            [
                user.name,
                user.get_role_display(),
                user.email,
                user.phone_number,
                user.get_gender_display() if user.gender else "",
                school_name,
                user.is_active,
                user.date_joined,
            ]
        )

    return [sheet]


ACTIVITY_LOOKUPS = {
    "school": "school_id",
    "role": "actor_role",
    "date_from": "created_at__date__gte",
    "date_to": "created_at__date__lte",
}


def activity_log_sheets(actor, params) -> list[Sheet]:
    """Super Admins only (see the catalogue), so no further scoping."""

    logs = narrow(ActivityLog.objects.all(), params, ACTIVITY_LOOKUPS).order_by("-created_at")

    sheet = Sheet(
        "Activity",
        [
            "When", "Person", "Email or mobile", "Role", "School", "Action",
            "Result", "HTTP status", "Method", "Path", "IP address", "Took (ms)", "Device",
        ],
    )

    for log in logs.iterator(chunk_size=2000):
        sheet.rows.append(
            [
                log.created_at,
                log.actor_name,
                log.actor_identifier,
                log.actor_role.replace("_", " ").title(),
                log.school_name,
                log.action,
                "Succeeded" if log.succeeded else "Failed",
                log.status_code,
                log.method,
                log.path,
                log.ip_address,
                log.duration_ms,
                log.user_agent,
            ]
        )

    return [sheet]


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    description: str
    roles: tuple[str, ...]
    filters: tuple[str, ...]
    build: Callable[..., list[Sheet]]


CLASS_FILTERS = ("school", "academic_year", "class_section", "school_class", "section")

REPORTS: dict[str, Report] = {
    report.key: report
    for report in (
        Report(
            "students",
            "Students",
            "Every student with class, roll number, photo and face status and their parents.",
            STAFF,
            CLASS_FILTERS,
            students_sheets,
        ),
        Report(
            "parents",
            "Parents",
            "Parents with their mobile number and the child they are linked to, in roll-number order.",
            STAFF,
            CLASS_FILTERS,
            parents_sheets,
        ),
        Report(
            "student-attendance",
            "Student attendance",
            "Day-by-day attendance of each student, with a per-student summary and attendance %.",
            STAFF,
            (*CLASS_FILTERS, "student", "date_from", "date_to", "status", "session_status"),
            student_attendance_sheets,
        ),
        Report(
            "teachers",
            "Teachers",
            "Teacher profiles with contact details, address and assigned class.",
            ADMINS,
            (*CLASS_FILTERS, "is_active"),
            teachers_sheets,
        ),
        Report(
            "teacher-attendance",
            "Teacher attendance",
            "Check-in and check-out times, hours worked and day type, with a per-teacher summary.",
            ADMINS,
            ("school", "teacher", "date_from", "date_to", "verification", "day_type"),
            teacher_attendance_sheets,
        ),
        Report(
            "schools",
            "Schools",
            "Every school with its contact details, admin and teacher and student counts.",
            SUPER,
            ("school", "school_status"),
            schools_sheets,
        ),
        Report(
            "users",
            "User accounts",
            "Every login account with role, contact details and status.",
            SUPER,
            ("school", "role", "is_active"),
            users_sheets,
        ),
        Report(
            "activity-logs",
            "Activity logs",
            "Every change, sign-in and report download, with who did it, when and from where.",
            SUPER,
            ("school", "role", "date_from", "date_to"),
            activity_log_sheets,
        ),
        Report(
            "my-attendance",
            "My attendance",
            "Your check-in and check-out times, hours worked and day type, with a summary.",
            TEACHER_ONLY,
            ("date_from", "date_to", "verification", "day_type"),
            teacher_attendance_sheets,
        ),
    )
}

ALL_KEY = "all"


def reports_for(actor) -> list[Report]:
    role = role_of(actor)

    return [report for report in REPORTS.values() if role in report.roles]


def scope_params(actor, params: dict) -> dict:
    """
    School Admins are pinned to their own school whatever they send;
    only Super Admins may pick one.
    """

    params = dict(params)

    if is_school_admin(actor):
        params.pop("school", None)

    return params


def build_report(actor, key: str, params: dict) -> list[Sheet]:
    """
    Build one report, or all the actor may see. In the bundle the
    attendance sheets are renamed after their report to keep them apart.
    """

    params = scope_params(actor, params)

    if key == ALL_KEY:
        sheets = []

        for report in reports_for(actor):
            for sheet in report.build(actor, params):
                if sheet.title == "Summary":
                    sheet.title = f"{report.title} summary"
                elif sheet.title == "Attendance":
                    sheet.title = report.title

                sheets.append(sheet)

        return sheets

    return REPORTS[key].build(actor, params)
