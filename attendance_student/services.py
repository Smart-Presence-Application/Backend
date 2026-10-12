"""Business logic for face registration and student attendance."""

import logging
import mimetypes
from datetime import date as date_type
from functools import partial
from pathlib import Path
from typing import Any, Iterable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from academics.models import ClassSection, Holiday, WorkingDay
from common.choices import AttendanceStatus, DayType
from common.exceptions import AIServiceUnavailable, AttendanceLocked, DuplicateRecord
from common.ordering import roll_order
from students.models import Student
from students.services import update_student_profile_image

from . import ai_client
from .ai_client import AIServiceError, ImagePayload
from .jobs import JobProgress, active_jobs, detach_upload, start_job
from .models import (
    AIJob,
    AIJobKind,
    AttendanceRecord,
    AttendanceSession,
    FaceRegistration,
    FaceRegistrationSource,
    RecordSource,
    SessionStatus,
)
from .selectors import is_attendance_admin
from .signals import attendance_finalized

logger = logging.getLogger(__name__)


def _announce_finalized(session: AttendanceSession, record_ids=None) -> None:
    """Send ``attendance_finalized`` once the transaction commits."""

    transaction.on_commit(
        partial(
            attendance_finalized.send,
            sender=AttendanceSession,
            session=session,
            record_ids=record_ids,
        )
    )


AI_STATUS_MAP = {
    "present": AttendanceStatus.PRESENT,
    "absent": AttendanceStatus.ABSENT,
}


def payload_from_upload(file_obj) -> ImagePayload:
    """
    Read an uploaded file without consuming it.

    The same upload may be saved as a profile image afterwards, so the
    file is rewound once its bytes have been read.
    """

    file_obj.seek(0)
    content = file_obj.read()
    file_obj.seek(0)

    if not content:
        raise ValidationError({"image": f"{file_obj.name} is empty."})

    return ImagePayload(
        name=Path(file_obj.name).name,
        content=content,
        content_type=getattr(file_obj, "content_type", None)
        or mimetypes.guess_type(file_obj.name)[0]
        or "application/octet-stream",
    )


def payload_from_profile_image(student: Student) -> ImagePayload:
    if not student.has_profile_image:
        raise ValidationError(
            {
                "profile_image": (
                    f"Student {student.student_id} has no profile image "
                    "to register."
                )
            }
        )

    image = student.profile_image

    try:
        image.open("rb")
        content = image.read()
    except (OSError, ValueError) as exc:
        logger.exception(
            "Could not read profile image for student %s",
            student.student_id,
        )
        raise ValidationError(
            {
                "profile_image": (
                    f"The profile image of student {student.student_id} "
                    "could not be read."
                )
            }
        ) from exc
    finally:
        image.close()

    return ImagePayload(
        name=Path(image.name).name,
        content=content,
        content_type=mimetypes.guess_type(image.name)[0]
        or "application/octet-stream",
    )


def _record_registration(*, student, source, actor) -> FaceRegistration:
    registration, _ = FaceRegistration.objects.update_or_create(
        student=student,
        defaults={
            "source": source,
            "registered_by": actor,
        },
    )

    return registration


def register_face_for_student(
    *,
    student: Student,
    actor,
    image_file=None,
) -> FaceRegistration:
    """
    Register a student's face with the AI service.

    With ``image_file`` the upload is registered and then kept as the
    student's profile image, so the picture on record is always the one
    the embedding was built from. Without it, the existing profile
    image is used and nothing is uploaded again.

    The AI call happens first: if the service rejects the image
    (no face, several faces, ...) nothing local changes. The signal that
    drops a registration on image change is skipped, since the new image
    is the registered face.
    """

    if image_file is not None:
        payload = payload_from_upload(image_file)
        source = FaceRegistrationSource.UPLOAD
    else:
        payload = payload_from_profile_image(student)
        source = FaceRegistrationSource.PROFILE_IMAGE

    ai_client.register_face(
        school_id=student.school_id,
        student_id=student.student_id,
        image=payload,
    )

    with transaction.atomic():
        if image_file is not None:
            student._skip_face_invalidation = True

            try:
                update_student_profile_image(
                    student=student,
                    image=image_file,
                )
            finally:
                student._skip_face_invalidation = False

        registration = _record_registration(
            student=student,
            source=source,
            actor=actor,
        )

    logger.info(
        "Face registered for student %s (school %s) from %s",
        student.student_id,
        student.school_id,
        source,
    )

    return registration


def set_student_photo(*, student: Student, image_file, actor) -> bool:
    """
    Make ``image_file`` the student's profile photo and registered face.

    The profile photo is the only picture a face is ever built from, so
    a new photo is registered straight away rather than leaving the
    student without a face. A photo the AI service rejects (no face,
    several faces, ...) is not saved: AIServiceError propagates and
    nothing changes. If the service is unreachable the photo is saved
    anyway; the stale face is dropped by the signal and the student can
    be registered from this photo later.

    Returns whether the face was registered.
    """

    try:
        register_face_for_student(
            student=student,
            actor=actor,
            image_file=image_file,
        )
    except AIServiceUnavailable:
        logger.warning(
            "AI service unavailable; saved photo for student %s without "
            "registering a face",
            student.student_id,
        )
        update_student_profile_image(student=student, image=image_file)
        return False

    return True


def registration_summary(results) -> dict:
    registered = sum(1 for item in results if item["registered"])

    return {
        "total": len(results),
        "registered": registered,
        "failed": len(results) - registered,
        "results": results,
    }


def register_faces(
    *,
    items: Iterable[tuple[str, Student | None, Any]],
    actor,
    progress: JobProgress | None = None,
    reported: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Register many faces, reporting each one separately.

    ``items`` yields ``(label, student, image_file)``; a None student
    means the label did not resolve and is reported as a failure. One
    bad image does not stop the rest, but if the AI service goes down
    the remaining items are reported as skipped rather than each
    waiting for its own timeout.

    With ``progress`` the running summary is published after every
    item, so a client polling the job sees results as they come in.
    ``reported`` are results already known (e.g. rejected file names),
    counted in that summary ahead of the rest.
    """

    reported = list(reported or [])
    results = []
    service_down = False

    def publish():
        if progress is None:
            return

        summary = registration_summary(reported + results)
        progress.update(
            processed=summary["total"],
            succeeded=summary["registered"],
            failed=summary["failed"],
            result=summary,
        )

    for label, student, image_file in items:
        result = {
            "label": label,
            "student": student.pk if student else None,
            "student_id": student.student_id if student else None,
        }

        if student is None:
            results.append({**result, "registered": False, "error": "Student not found in your scope."})
            publish()
            continue

        if service_down:
            results.append({**result, "registered": False, "error": "Skipped: AI service is unavailable."})
            publish()
            continue

        if progress is not None:
            progress.stage(f"Registering {label}")

        try:
            register_face_for_student(
                student=student,
                actor=actor,
                image_file=image_file,
            )
        except AIServiceError as exc:
            results.append({**result, "registered": False, "error": exc.message})
        except ValidationError as exc:
            results.append({**result, "registered": False, "error": "; ".join(exc.messages)})
        except AIServiceUnavailable:
            service_down = True
            results.append({**result, "registered": False, "error": "AI service is unavailable."})
        else:
            results.append({**result, "registered": True, "error": None})

        publish()

    return results


def delete_face_for_student(*, student: Student) -> bool:
    """
    Delete a student's embedding from the AI service and our record.

    Unlike the automatic clean-up in signals this is an explicit
    request, so an unreachable service is reported (503) and the local
    row is kept, letting the caller retry.

    Returns whether the AI service actually held an embedding.
    """

    existed = ai_client.delete_face(
        school_id=student.school_id,
        student_id=student.student_id,
    )

    FaceRegistration.objects.filter(student=student).delete()

    logger.info(
        "Face deleted for student %s (school %s)",
        student.student_id,
        student.school_id,
    )

    return existed


def start_face_registration_job(
    *,
    kind: str,
    items: Iterable[tuple[str, Student | None, Any]],
    actor,
    rejected: Iterable[dict[str, Any]] = (),
) -> AIJob:
    """
    Queue ``register_faces`` for ``items`` and return the job.

    Uploads are copied into memory and students passed by primary key,
    since the request and its temporary files are gone by the time the
    job runs. ``rejected`` are failures already decided by the caller;
    they are part of the job's summary from the start.
    """

    prepared = [
        (
            label,
            student.pk if student is not None else None,
            detach_upload(image_file) if image_file is not None else None,
        )
        for label, student, image_file in items
    ]
    rejected = list(rejected)

    def work(progress: JobProgress) -> dict:
        students = Student.objects.in_bulk(
            [pk for _, pk, _ in prepared if pk is not None],
        )
        results = register_faces(
            items=(
                (label, students.get(pk) if pk is not None else None, image_file)
                for label, pk, image_file in prepared
            ),
            actor=actor,
            progress=progress,
            reported=rejected,
        )
        summary = registration_summary(rejected + results)
        progress.stage(
            f"{summary['registered']} of {summary['total']} face(s) registered."
        )
        return summary

    initial = registration_summary(rejected)

    return start_job(
        kind=kind,
        actor=actor,
        work=work,
        message="Queued: waiting to register faces.",
        total=len(rejected) + len(prepared),
        processed=initial["total"],
        failed=initial["failed"],
        result=initial,
    )


def start_student_photo_job(*, student: Student, image_file, actor) -> AIJob:
    """
    Make ``image_file`` the student's photo and face in the background.

    Runs ``set_student_photo``: a photo the AI service rejects fails the
    job and is not saved, so the old photo and face stay; if the service
    is unreachable the photo is saved without a face.
    """

    if active_jobs().filter(kind=AIJobKind.STUDENT_PHOTO, student=student).exists():
        raise DuplicateRecord(
            "A photo for this student is still being processed. "
            "Wait for it to finish, then try again."
        )

    upload = detach_upload(image_file)
    student_pk = student.pk

    def work(progress: JobProgress) -> dict:
        current = Student.objects.filter(pk=student_pk).first()

        if current is None:
            raise ValidationError({"student": "The student no longer exists."})

        progress.stage("Registering the face from the new photo.")
        registered = set_student_photo(
            student=current,
            image_file=upload,
            actor=actor,
        )
        progress.update(processed=1, succeeded=int(registered), failed=int(not registered))
        progress.stage(
            "Photo saved and face registered."
            if registered
            else "Photo saved. The AI service is unavailable, so the face "
            "was not registered yet; register it from the profile photo later."
        )
        return {"student": student_pk, "face_registered": registered}

    return start_job(
        kind=AIJobKind.STUDENT_PHOTO,
        actor=actor,
        work=work,
        message="Queued: waiting to register the face.",
        student=student,
        total=1,
    )


def validate_attendance_date(
    *,
    class_section: ClassSection,
    date: date_type,
) -> None:
    """
    Attendance can only be taken on a past or present school day that
    falls inside the class-section's academic year.
    """

    if date > timezone.localdate():
        raise ValidationError({"date": "Attendance cannot be marked for a future date."})

    academic_year = class_section.academic_year

    if not (academic_year.start_date <= date <= academic_year.end_date):
        raise ValidationError(
            {"date": f"The date is outside the academic year {academic_year.name}."}
        )

    school_id = academic_year.school_id

    holiday = Holiday.objects.filter(school_id=school_id, date=date).first()

    if holiday is not None:
        raise ValidationError({"date": f"{date} is a holiday ({holiday.title})."})

    if WorkingDay.objects.filter(
        school_id=school_id,
        date=date,
        day_type__in=[DayType.HOLIDAY, DayType.WEEKEND],
    ).exists():
        raise ValidationError({"date": f"{date} is not a working day."})


AUTO_WORKING_DAY_REMARK = "Marked automatically: class attendance was taken."


def mark_working_day(*, class_section: ClassSection, date: date_type) -> None:
    """
    Record ``date`` as a working day once attendance is taken on it.

    Only fills a gap in the calendar: a date the school already set
    (working, event, holiday or weekend) is left as it is. Holidays and
    weekends never get here anyway, since attendance is refused on them.
    """

    academic_year = class_section.academic_year
    _, created = WorkingDay.objects.get_or_create(
        school_id=academic_year.school_id,
        date=date,
        defaults={
            "academic_year": academic_year,
            "day_type": DayType.WORKING,
            "remarks": AUTO_WORKING_DAY_REMARK,
        },
    )

    if created:
        logger.info("Marked %s as a working day for school %s (attendance taken)", date, academic_year.school_id)


def ensure_editable(*, session: AttendanceSession, actor) -> None:
    if session.is_locked and not is_attendance_admin(actor):
        raise AttendanceLocked()


def _section_students(class_section: ClassSection):
    return list(
        Student.objects.filter(class_section=class_section)
        .select_related("face_registration")
        .order_by(roll_order())
    )


def has_registered_face(student: Student) -> bool:
    try:
        return student.face_registration is not None
    except FaceRegistration.DoesNotExist:
        return False


def _parse_ai_result(result: dict) -> tuple[dict[str, str], dict[str, float]]:
    """
    Map the AI result to our statuses (its case is ignored) and the
    best similarity per student ID.
    """

    statuses = {}

    for item in result.get("students") or []:
        student_id = str(item.get("student_id", "")).strip().upper()
        status = AI_STATUS_MAP.get(str(item.get("status", "")).lower())

        if student_id and status:
            statuses[student_id] = status

    similarities: dict[str, float] = {}

    for match in result.get("matches") or []:
        student_id = str(match.get("student_id", "")).strip().upper()
        score = match.get("similarity")

        if student_id and isinstance(score, (int, float)):
            similarities[student_id] = max(score, similarities.get(student_id, score))

    return statuses, similarities


def check_can_verify(
    *,
    class_section: ClassSection,
    date: date_type,
    actor,
) -> tuple[list[Student], list[str]]:
    """
    Everything that must hold before photos go to the AI service.

    Returns the section's students and the IDs of those with a
    registered face. Called before queuing a verification, so a bad
    request is refused at once rather than after a wait.
    """

    validate_attendance_date(class_section=class_section, date=date)

    existing = AttendanceSession.objects.filter(
        class_section=class_section,
        date=date,
    ).first()

    if existing is not None:
        ensure_editable(session=existing, actor=actor)

    students = _section_students(class_section)

    if not students:
        raise ValidationError({"class_section": "This class section has no students."})

    registered_ids = [s.student_id for s in students if has_registered_face(s)]

    if not registered_ids:
        raise ValidationError(
            {
                "detail": (
                    "No student in this class section has a registered "
                    "face. Register faces before verifying attendance."
                )
            }
        )

    return students, registered_ids


def verify_attendance(
    *,
    class_section: ClassSection,
    date: date_type,
    image_files: list,
    actor,
    progress: JobProgress | None = None,
) -> AttendanceSession:
    """
    Run AI verification for a class-section and save it as a draft.

    Only students of the section with a registered face are sent to the
    AI service; everyone else is recorded absent with
    ``face_registered=False`` so the teacher can see why.

    Running it again on a draft refreshes the AI results but keeps any
    status a person set by hand. A locked session can only be re-run by
    an admin, and stays locked.

    The AI call is deliberately made outside any transaction so it holds
    no row locks; editability is re-checked under the lock afterwards in
    case the session was locked meanwhile. ``bulk_update`` bypasses
    ``auto_now``, so ``updated_at`` is stamped by hand.
    """

    students, registered_ids = check_can_verify(
        class_section=class_section,
        date=date,
        actor=actor,
    )

    school_id = class_section.academic_year.school_id

    if progress is not None:
        progress.stage(
            f"Recognising faces in {len(image_files)} photo(s). "
            "This can take a few minutes."
        )

    result = ai_client.verify_attendance(
        school_id=school_id,
        student_ids=registered_ids,
        images=[payload_from_upload(f) for f in image_files],
    )

    if progress is not None:
        progress.stage("Saving the draft attendance.")

    statuses, similarities = _parse_ai_result(result)

    with transaction.atomic():
        session, _ = AttendanceSession.objects.select_for_update().get_or_create(
            class_section=class_section,
            date=date,
            defaults={
                "school_id": school_id,
                "created_by": actor,
            },
        )
        mark_working_day(class_section=class_section, date=date)

        ensure_editable(session=session, actor=actor)

        session.image_count = int(result.get("image_count") or len(image_files))
        session.detected_faces = int(result.get("detected_faces") or 0)
        session.verified_at = timezone.now()
        session.save(
            update_fields=[
                "image_count",
                "detected_faces",
                "verified_at",
                "updated_at",
            ],
        )

        existing_records = {
            record.student_id: record
            for record in session.records.select_for_update()
        }

        to_create = []
        to_update = []

        for student in students:
            registered = has_registered_face(student)
            ai_status = (
                statuses.get(student.student_id, AttendanceStatus.ABSENT)
                if registered
                else None
            )
            record = existing_records.get(student.pk)

            if record is None:
                to_create.append(
                    AttendanceRecord(
                        session=session,
                        student=student,
                        status=ai_status or AttendanceStatus.ABSENT,
                        source=RecordSource.AI,
                        ai_status=ai_status,
                        similarity=similarities.get(student.student_id),
                        face_registered=registered,
                        updated_by=actor,
                    )
                )
                continue

            record.ai_status = ai_status
            record.similarity = similarities.get(student.student_id)
            record.face_registered = registered

            if record.source != RecordSource.MANUAL:
                record.status = ai_status or AttendanceStatus.ABSENT
                record.updated_by = actor

            to_update.append(record)

        AttendanceRecord.objects.bulk_create(to_create)

        if to_update:
            now = timezone.now()

            for record in to_update:
                record.updated_at = now

            AttendanceRecord.objects.bulk_update(
                to_update,
                fields=[
                    "status",
                    "ai_status",
                    "similarity",
                    "face_registered",
                    "updated_by",
                    "updated_at",
                ],
            )

    logger.info(
        "Attendance verified for class section %s on %s: %s present of %s",
        class_section.id,
        date,
        sum(1 for s in statuses.values() if s == AttendanceStatus.PRESENT),
        len(students),
    )

    return session


def start_verification_job(
    *,
    class_section: ClassSection,
    date: date_type,
    image_files: list,
    actor,
) -> AIJob:
    """
    Check the request now, then run ``verify_attendance`` in the
    background. The job's result names the saved session.

    Only one verification per class-section and date runs at a time:
    two at once would race to write the same draft.
    """

    check_can_verify(class_section=class_section, date=date, actor=actor)

    if active_jobs().filter(
        kind=AIJobKind.ATTENDANCE_VERIFY,
        class_section=class_section,
        date=date,
    ).exists():
        raise DuplicateRecord(
            "Attendance for this class section and date is already being "
            "verified. Wait for it to finish."
        )

    uploads = [detach_upload(f) for f in image_files]
    section_pk = class_section.pk

    def work(progress: JobProgress) -> dict:
        section = ClassSection.objects.select_related("academic_year").get(pk=section_pk)
        session = verify_attendance(
            class_section=section,
            date=date,
            image_files=uploads,
            actor=actor,
            progress=progress,
        )
        progress.update(processed=len(uploads))
        progress.stage("Attendance verified and saved as draft.")
        return {"session": session.pk}

    return start_job(
        kind=AIJobKind.ATTENDANCE_VERIFY,
        actor=actor,
        work=work,
        message="Queued: waiting to recognise faces.",
        class_section=class_section,
        date=date,
        total=len(uploads),
    )


@transaction.atomic
def create_manual_session(
    *,
    class_section: ClassSection,
    date: date_type,
    actor,
    records: list[dict[str, Any]] | None = None,
) -> AttendanceSession:
    """
    Start a draft without the AI service, e.g. when it is down.

    Every student of the section gets a record; those not listed in
    ``records`` default to absent.
    """

    validate_attendance_date(class_section=class_section, date=date)

    if AttendanceSession.objects.filter(class_section=class_section, date=date).exists():
        raise ValidationError(
            {"date": "Attendance for this class section and date already exists. Edit it instead."}
        )

    students = _section_students(class_section)

    if not students:
        raise ValidationError({"class_section": "This class section has no students."})

    provided = {item["student"].pk: item for item in records or []}
    section_ids = {s.pk for s in students}
    unknown = set(provided) - section_ids

    if unknown:
        raise ValidationError(
            {"records": f"Students {sorted(unknown)} are not in this class section."}
        )

    session = AttendanceSession.objects.create(
        school_id=class_section.academic_year.school_id,
        class_section=class_section,
        date=date,
        created_by=actor,
    )
    mark_working_day(class_section=class_section, date=date)

    AttendanceRecord.objects.bulk_create(
        [
            AttendanceRecord(
                session=session,
                student=student,
                status=provided.get(student.pk, {}).get("status", AttendanceStatus.ABSENT),
                remarks=provided.get(student.pk, {}).get("remarks", ""),
                source=RecordSource.MANUAL,
                face_registered=has_registered_face(student),
                updated_by=actor,
            )
            for student in students
        ]
    )

    return session


@transaction.atomic
def update_records(
    *,
    session: AttendanceSession,
    actor,
    records: list[dict[str, Any]],
) -> AttendanceSession:
    """
    Apply manual corrections to a session.

    A student may be added if they belong to the session's
    class-section (e.g. enrolled after the AI run). Teachers may only
    edit drafts; admins may edit at any time. Parents are only notified
    of changes to a locked session; drafts are announced at lock time.
    """

    session = AttendanceSession.objects.select_for_update().get(pk=session.pk)
    ensure_editable(session=session, actor=actor)

    existing = {
        record.student_id: record
        for record in session.records.select_for_update()
    }

    errors = {}

    for item in records:
        student = item["student"]
        record = existing.get(student.pk)

        if record is None:
            if student.class_section_id != session.class_section_id:
                errors[str(student.pk)] = "Student is not part of this attendance."
                continue

            record = AttendanceRecord(
                session=session,
                student=student,
                face_registered=has_registered_face(student),
            )
            existing[student.pk] = record

        record.status = item["status"]
        record.source = RecordSource.MANUAL
        record.updated_by = actor

        if "remarks" in item:
            record.remarks = item["remarks"]

    if errors:
        raise ValidationError({"records": errors})

    for item in records:
        existing[item["student"].pk].save()

    session.save(update_fields=["updated_at"])

    if session.is_locked:
        _announce_finalized(
            session,
            record_ids=[existing[item["student"].pk].pk for item in records],
        )

    return session


@transaction.atomic
def lock_session(*, session: AttendanceSession, actor) -> AttendanceSession:
    session = AttendanceSession.objects.select_for_update().get(pk=session.pk)

    if session.is_locked:
        raise AttendanceLocked("Attendance is already locked.")

    session.status = SessionStatus.LOCKED
    session.locked_by = actor
    session.locked_at = timezone.now()
    session.save(update_fields=["status", "locked_by", "locked_at", "updated_at"])

    logger.info("Attendance session %s locked by user %s", session.pk, actor.pk)

    _announce_finalized(session)

    return session


@transaction.atomic
def unlock_session(*, session: AttendanceSession, actor) -> AttendanceSession:
    session = AttendanceSession.objects.select_for_update().get(pk=session.pk)

    if not session.is_locked:
        raise ValidationError({"detail": "Attendance is not locked."})

    session.status = SessionStatus.DRAFT
    session.locked_by = None
    session.locked_at = None
    session.save(update_fields=["status", "locked_by", "locked_at", "updated_at"])

    logger.info("Attendance session %s unlocked by user %s", session.pk, actor.pk)

    return session


@transaction.atomic
def delete_session(*, session: AttendanceSession, actor) -> None:
    """
    Delete a session and all its records, locked or not.

    Parent notifications sent about these records are deleted with them.
    """

    session = AttendanceSession.objects.select_for_update().get(pk=session.pk)
    session_id = session.pk

    session.delete()

    logger.info("Attendance session %s deleted by user %s", session_id, actor.pk)
