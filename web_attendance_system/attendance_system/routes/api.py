from datetime import date, datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from flask_login import current_user, login_required

from attendance_system.extensions import db
from attendance_system.models import Attendance, Course, Institute, Role, Student, Timetable, TemporaryTimetableAdjustment
from attendance_system.services.access import role_required
from attendance_system.services.face_service import identify_students
from attendance_system.services.report_service import slot_matches_student


api_bp = Blueprint("api", __name__)


def _json_error(message, status=400):
    return jsonify({"success": False, "message": message}), status


@api_bp.get("/courses")
def courses():
    institute_name = request.args.get("institute", "").strip()
    if not institute_name:
        return jsonify([])

    institute = Institute.query.filter(Institute.name.ilike(institute_name)).first()
    if not institute:
        return jsonify([])

    rows = Course.query.filter_by(institute_id=institute.id).order_by(Course.name).all()
    return jsonify([{"id": row.id, "name": row.name, "code": row.code, "duration_months": row.duration_months} for row in rows])


def _resolve_slot(slot_ref):
    slot_ref = str(slot_ref)
    if slot_ref.startswith("temporary-"):
        slot_id = int(slot_ref.split("-", 1)[1])
        return TemporaryTimetableAdjustment.query.filter_by(id=slot_id).first_or_404()
    slot_id = int(slot_ref.split("-", 1)[1]) if slot_ref.startswith("timetable-") else int(slot_ref)
    return Timetable.query.filter_by(id=slot_id).first_or_404()


@api_bp.post("/attendance/mark/<slot_ref>")
@login_required
@role_required(Role.TEACHER.value)
def mark_attendance(slot_ref):
    slot = _resolve_slot(slot_ref)
    if slot.teacher.user_id != current_user.id:
        return _json_error("Unauthorized lecture slot.", 403)

    now = datetime.now()
    if isinstance(slot, TemporaryTimetableAdjustment):
        slot_is_live = slot.is_live(now.strftime("%A"), now.time(), current_date=now.date())
    else:
        slot_is_live = slot.is_live(now.strftime("%A"), now.time())
    if not slot_is_live:
        return _json_error("Attendance can only be marked during the scheduled lecture time.", 400)

    payload = request.get_json() or {}
    frame = payload.get("frame")
    if not frame:
        return _json_error("Frame data is required.")

    students = Student.query.filter_by(institute_id=current_user.institute_id).all()
    students = [student for student in students if slot_matches_student(student, slot)]

    try:
        matches = identify_students(frame, students)
    except RuntimeError as exc:
        return _json_error(str(exc), 501)

    if not matches:
        return _json_error("No face detected in the camera frame.", 404)

    marked_students = []
    duplicate_students = []
    unknown_faces = 0
    overlays = []

    for match in matches:
        if not match.get("matched"):
            unknown_faces += 1
            overlays.append(
                {
                    "name": "Unknown face",
                    "roll_number": "Unregistered",
                    "status": "unknown",
                    "location": match["location"],
                }
            )
            continue

        student = match["student"]
        if isinstance(slot, TemporaryTimetableAdjustment):
            existing = Attendance.query.filter_by(
                student_id=student.id,
                temporary_adjustment_id=slot.id,
                date=date.today(),
            ).first()
        else:
            existing = Attendance.query.filter_by(
                student_id=student.id,
                timetable_id=slot.id,
                date=date.today(),
            ).first()

        overlay = {
            "name": student.name,
            "roll_number": student.roll_number,
            "status": "duplicate" if existing else "marked",
            "location": match["location"],
        }
        overlays.append(overlay)

        if existing:
            duplicate_students.append(student.name)
            continue

        attendance = Attendance(
            student_id=student.id,
            timetable_id=None if isinstance(slot, TemporaryTimetableAdjustment) else slot.id,
            temporary_adjustment_id=slot.id if isinstance(slot, TemporaryTimetableAdjustment) else None,
            subject=slot.subject,
            date=date.today(),
            time=now.time().replace(microsecond=0),
            status="present",
        )
        db.session.add(attendance)
        marked_students.append(student.name)

    if marked_students:
        db.session.commit()
    else:
        db.session.rollback()

    if not marked_students and duplicate_students:
        return jsonify(
            {
                "success": True,
                "duplicate": True,
                "message": "All recognized students were already marked for this lecture.",
                "duplicates": duplicate_students,
                "recognized_count": len(matches),
                "unknown_count": unknown_faces,
                "overlays": overlays,
            }
        )

    return jsonify(
        {
            "success": True,
            "message": f"Attendance processed for {len(matches)} recognized face(s).",
            "subject": slot.subject,
            "recognized_count": len(matches),
            "marked_count": len(marked_students),
            "duplicate_count": len(duplicate_students),
            "unknown_count": unknown_faces,
            "marked_students": marked_students,
            "duplicates": duplicate_students,
            "overlays": overlays,
            "slot_kind": getattr(slot, "slot_kind", "weekly"),
        }
    )
