from datetime import date

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from attendance_system.models import Role
from attendance_system.services.access import role_required
from attendance_system.services.report_service import (
    build_student_attendance_report,
    get_student_temporary_adjustments,
    get_student_weekly_slots,
)


student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.get("/dashboard")
@login_required
@role_required(Role.STUDENT.value)
def dashboard():
    student = current_user.student_profile
    weekly_slots = get_student_weekly_slots(student)
    temporary_slots = get_student_temporary_adjustments(student)
    report = build_student_attendance_report(student, weekly_slots, temporary_slots)
    dashboard_is_low = report["is_low"]
    dashboard_warning_rows = report["warning_rows"]
    if report["monthly_source"] == "excel":
        dashboard_is_low = report["monthly_imported_percentage"] < 75
        if not dashboard_is_low:
            dashboard_warning_rows = []
    today = date.today()
    today_name = today.strftime("%A")
    today_slots = [slot for slot in weekly_slots if slot.day == today_name]
    today_slots.extend([slot for slot in temporary_slots if slot.adjustment_date == today])
    today_slots = sorted(today_slots, key=lambda slot: slot.start_time)

    return render_template(
        "student/dashboard.html",
        student=student,
        timetable=weekly_slots,
        temporary_slots=temporary_slots,
        subject_rows=report["subject_rows"],
        overall_percentage=report["monthly_imported_percentage"] if report["monthly_source"] == "excel" else report["overall_percentage"],
        total_present=report["monthly_imported_present"] if report["monthly_source"] == "excel" else report["total_present"],
        total_lectures=report["monthly_imported_total"] if report["monthly_source"] == "excel" else report["total_lectures"],
        warning_rows=dashboard_warning_rows,
        is_low=dashboard_is_low,
        chart_labels=report["chart_labels"],
        chart_values=report["chart_values"],
        monthly_rows=report["monthly_rows"],
        monthly_source=report["monthly_source"],
        monthly_match_name=report["monthly_match_name"],
        monthly_match_roll=report["monthly_match_roll"],
        monthly_imported_present=report["monthly_imported_present"],
        monthly_imported_total=report["monthly_imported_total"],
        monthly_imported_percentage=report["monthly_imported_percentage"],
        today_name=today_name,
        today_slots=today_slots,
        active_page="dashboard",
    )


@student_bp.get("/timetable")
@login_required
@role_required(Role.STUDENT.value)
def view_timetable():
    student = current_user.student_profile
    weekly_slots = get_student_weekly_slots(student)
    temporary_slots = get_student_temporary_adjustments(student, include_past=False)
    report = build_student_attendance_report(student, weekly_slots, temporary_slots)
    return render_template(
        "student/timetable.html",
        student=student,
        grouped_timetable=report["grouped_timetable"],
        timetable_matrix=report["timetable_matrix"],
        temporary_slots=temporary_slots,
        active_page="timetable",
    )


@student_bp.get("/attendance/report")
@login_required
@role_required(Role.STUDENT.value)
def attendance_report():
    student = current_user.student_profile
    weekly_slots = get_student_weekly_slots(student)
    temporary_slots = get_student_temporary_adjustments(student)
    report = build_student_attendance_report(student, weekly_slots, temporary_slots)
    return render_template(
        "student/attendance_report.html",
        student=student,
        records=report["records"],
        subject_rows=report["subject_rows"],
        chart_labels=report["chart_labels"],
        chart_values=report["chart_values"],
        monthly_rows=report["monthly_rows"],
        overall_percentage=report["overall_percentage"],
        total_present=report["total_present"],
        total_lectures=report["total_lectures"],
        warning_rows=dashboard_warning_rows,
        is_low=dashboard_is_low,
        temporary_slots=temporary_slots,
        active_page="attendance_report",
    )
