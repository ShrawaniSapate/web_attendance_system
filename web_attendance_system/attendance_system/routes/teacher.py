from datetime import date, datetime

from flask import Blueprint, flash, render_template
from flask_login import current_user, login_required

from attendance_system.models import Role, Timetable, TemporaryTimetableAdjustment
from attendance_system.services.access import role_required
from attendance_system.services.report_service import (
    build_teacher_defaulter_rows,
    build_teacher_monthly_assessment,
    build_teacher_subject_summary,
    build_timetable_matrix,
    group_timetable_entries,
)


teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _teacher_timetable(teacher_id):
    return Timetable.query.filter_by(teacher_id=teacher_id).order_by(Timetable.day, Timetable.start_time).all()


def _teacher_adjustments(teacher_id):
    return (
        TemporaryTimetableAdjustment.query.filter_by(teacher_id=teacher_id)
        .order_by(TemporaryTimetableAdjustment.adjustment_date.desc(), TemporaryTimetableAdjustment.start_time)
        .all()
    )


def _today_teacher_slots(teacher_id):
    today = date.today()
    today_name = today.strftime("%A")
    weekly_slots = [slot for slot in _teacher_timetable(teacher_id) if slot.day == today_name]
    temporary_slots = (
        TemporaryTimetableAdjustment.query.filter_by(teacher_id=teacher_id, adjustment_date=today)
        .order_by(TemporaryTimetableAdjustment.start_time)
        .all()
    )
    return sorted([*weekly_slots, *temporary_slots], key=lambda slot: slot.start_time)


def _attendance_slot_options(teacher_id):
    weekly_slots = _teacher_timetable(teacher_id)
    temporary_slots = _teacher_adjustments(teacher_id)
    return sorted(
        [*weekly_slots, *temporary_slots],
        key=lambda slot: (
            0 if getattr(slot, "slot_kind", "weekly") == "emergency" else 1,
            getattr(slot, "adjustment_date", date.max),
            slot.day,
            slot.start_time,
        ),
    )


def _resolve_slot(slot_ref):
    if str(slot_ref).startswith("temporary-"):
        slot_id = int(str(slot_ref).split("-", 1)[1])
        return TemporaryTimetableAdjustment.query.filter_by(id=slot_id).first_or_404()
    slot_id = int(str(slot_ref).split("-", 1)[1]) if str(slot_ref).startswith("timetable-") else int(slot_ref)
    return Timetable.query.filter_by(id=slot_id).first_or_404()


def _teacher_scope_summary(weekly_slots, temporary_slots):
    all_slots = [*weekly_slots, *temporary_slots]
    subjects = sorted({slot.subject for slot in all_slots if getattr(slot, "subject", None)})
    courses = sorted({(slot.course_record.name if getattr(slot, "course_record", None) else slot.course) for slot in all_slots if getattr(slot, "course", None)})
    classes = []
    for slot in all_slots:
        classroom = getattr(slot, "classroom", None)
        if classroom:
            label = classroom.name
            if classroom.display_division:
                label = f"{label} ({classroom.display_division})"
            classes.append(label)
    return {
        "subjects": subjects,
        "courses": sorted(set(courses)),
        "classes": sorted(set(classes)),
    }


@teacher_bp.get("/dashboard")
@login_required
@role_required(Role.TEACHER.value)
def dashboard():
    teacher = current_user.teacher_profile
    timetable = _teacher_timetable(teacher.id)
    temporary_slots = _teacher_adjustments(teacher.id)
    records, subject_summary = build_teacher_subject_summary(teacher.id)
    monthly_assessment = build_teacher_monthly_assessment(teacher.id)
    today_name = date.today().strftime("%A")
    scope = _teacher_scope_summary(timetable, temporary_slots)

    return render_template(
        "teacher/dashboard.html",
        teacher=teacher,
        timetable=timetable,
        temporary_slots=temporary_slots,
        records=records,
        subject_summary=subject_summary,
        monthly_assessment=monthly_assessment,
        today=date.today(),
        today_name=today_name,
        today_slots=_today_teacher_slots(teacher.id),
        assigned_subjects=scope["subjects"],
        assigned_courses=scope["courses"],
        assigned_classes=scope["classes"],
        active_page="dashboard",
    )


@teacher_bp.get("/timetable")
@login_required
@role_required(Role.TEACHER.value)
def view_timetable():
    teacher = current_user.teacher_profile
    timetable = _teacher_timetable(teacher.id)
    temporary_slots = _teacher_adjustments(teacher.id)
    return render_template(
        "teacher/timetable.html",
        teacher=teacher,
        grouped_timetable=group_timetable_entries(timetable),
        timetable_matrix=build_timetable_matrix(timetable),
        temporary_slots=temporary_slots,
        active_page="timetable",
    )


@teacher_bp.get("/attendance/start")
@login_required
@role_required(Role.TEACHER.value)
def start_attendance():
    teacher = current_user.teacher_profile
    timetable = _teacher_timetable(teacher.id)
    return render_template(
        "teacher/attendance_start.html",
        teacher=teacher,
        timetable=timetable,
        attendance_slots=_attendance_slot_options(teacher.id),
        today=date.today(),
        today_name=date.today().strftime("%A"),
        today_slots=_today_teacher_slots(teacher.id),
        active_page="start_attendance",
    )


@teacher_bp.get("/attendance/report")
@login_required
@role_required(Role.TEACHER.value)
def attendance_report():
    teacher = current_user.teacher_profile
    records, subject_summary = build_teacher_subject_summary(teacher.id)
    defaulter_rows = build_teacher_defaulter_rows(teacher)
    scope = _teacher_scope_summary(_teacher_timetable(teacher.id), _teacher_adjustments(teacher.id))
    return render_template(
        "teacher/attendance_report.html",
        teacher=teacher,
        records=records,
        subject_summary=subject_summary,
        defaulter_rows=defaulter_rows,
        total_records=len(records),
        assigned_subjects=scope["subjects"],
        assigned_courses=scope["courses"],
        assigned_classes=scope["classes"],
        active_page="attendance_report",
    )


@teacher_bp.get("/attendance/defaulters/print")
@login_required
@role_required(Role.TEACHER.value)
def print_defaulters():
    teacher = current_user.teacher_profile
    defaulter_rows = build_teacher_defaulter_rows(teacher)
    scope = _teacher_scope_summary(_teacher_timetable(teacher.id), _teacher_adjustments(teacher.id))
    return render_template(
        "teacher/defaulters_print.html",
        teacher=teacher,
        defaulter_rows=defaulter_rows,
        assigned_subjects=scope["subjects"],
        title="Teacher Defaulters List",
    )


@teacher_bp.get("/attendance/<slot_ref>")
@login_required
@role_required(Role.TEACHER.value)
def attendance_room(slot_ref):
    teacher = current_user.teacher_profile
    slot = _resolve_slot(slot_ref)
    if slot.teacher.user_id != current_user.id:
        flash("You do not have access to this lecture slot.", "danger")
        return render_template("teacher/attendance_room.html", teacher=teacher, slot=None, active_page="start_attendance")
    now = datetime.now()
    if isinstance(slot, TemporaryTimetableAdjustment):
        slot_is_live = slot.is_live(now.strftime("%A"), now.time(), current_date=now.date())
    else:
        slot_is_live = slot.is_live(now.strftime("%A"), now.time())
    return render_template(
        "teacher/attendance_room.html",
        teacher=teacher,
        slot=slot,
        slot_ref=slot.slot_ref,
        slot_is_live=slot_is_live,
        current_datetime=now,
        active_page="start_attendance",
    )
