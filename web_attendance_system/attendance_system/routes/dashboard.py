from datetime import date

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

from attendance_system.models import AttendanceRecord, Course, Role, Subject, TimetableEntry, User


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/dashboard")
@login_required
def home():
    if current_user.role == Role.ADMIN.value:
        return render_template(
            "admin/dashboard.html",
            total_courses=Course.query.filter_by(institute_id=current_user.institute_id).count(),
            total_users=User.query.filter_by(institute_id=current_user.institute_id).count(),
            total_subjects=Subject.query.join(Course).filter(Course.institute_id == current_user.institute_id).count(),
            today_attendance=AttendanceRecord.query.filter(AttendanceRecord.attendance_date == date.today()).count(),
        )

    if current_user.role == Role.FACULTY.value:
        faculty = current_user.faculty_profile
        timetable = TimetableEntry.query.filter_by(faculty_id=faculty.id).order_by(TimetableEntry.day_of_week, TimetableEntry.start_time).all()
        return render_template("faculty/dashboard.html", faculty=faculty, timetable=timetable)

    if current_user.role == Role.STUDENT.value:
        student = current_user.student_profile
        total_classes = AttendanceRecord.query.filter_by(student_id=student.id).count()
        present_classes = AttendanceRecord.query.filter_by(student_id=student.id, status="present").count()
        percentage = round((present_classes / total_classes) * 100, 2) if total_classes else 0
        recent_records = AttendanceRecord.query.filter_by(student_id=student.id).order_by(AttendanceRecord.marked_at.desc()).limit(10).all()
        return render_template(
            "student/dashboard.html",
            student=student,
            total_classes=total_classes,
            present_classes=present_classes,
            percentage=percentage,
            recent_records=recent_records,
        )

    abort(403)
