import csv
import re
from datetime import date, datetime
from io import StringIO
from werkzeug.utils import secure_filename

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from attendance_system.extensions import db
from attendance_system.models import Attendance, Classroom, Course, Role, Student, Subject, Teacher, TemporaryTimetableAdjustment, Timetable, User
from attendance_system.services.access import role_required
from attendance_system.services.face_service import encode_uploaded_face
from attendance_system.services.report_service import build_admin_attendance_overview, build_timetable_matrix, group_timetable_entries
from attendance_system.services.storage_service import delete_if_exists, save_bytes
from attendance_system.services.external_attendance_service import summarize_external_attendance_for_students


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z\s.'-]{1,99}$")
ROLL_RE = re.compile(r"^[A-Za-z0-9/_-]{2,30}$")
TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\s&().,'/-]{1,119}$")
ALLOWED_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}


def _parse_time(value):
    return datetime.strptime(value, "%H:%M").time()


def _valid_email(email: str) -> bool:
    return bool(EMAIL_RE.fullmatch(email or ""))


def _valid_name(value: str) -> bool:
    return bool(NAME_RE.fullmatch(value or ""))


def _valid_roll_number(value: str) -> bool:
    return bool(ROLL_RE.fullmatch(value or ""))


def _valid_text(value: str, max_length: int = 120) -> bool:
    return bool(value) and len(value) <= max_length and bool(TEXT_RE.fullmatch(value))


def _validate_catalog_name(value: str, label: str) -> str | None:
    if not _valid_text(value, 120):
        return f"Enter a valid {label} name."
    return None


def _valid_short_code(value: str) -> bool:
    return len(value) <= 30 and bool(re.fullmatch(r"[A-Za-z0-9/_-]*", value or ""))


def _valid_password(password: str) -> bool:
    if not password or len(password) < 8:
        return False
    checks = [
        re.search(r"[A-Z]", password),
        re.search(r"[a-z]", password),
        re.search(r"\d", password),
        re.search(r"[^A-Za-z0-9]", password),
    ]
    return all(checks)


def _admin_data():
    institute_id = current_user.institute_id
    today = date.today()
    today_name = today.strftime("%A")
    students = Student.query.filter_by(institute_id=institute_id).order_by(Student.name).all()
    teachers = Teacher.query.filter_by(institute_id=institute_id).order_by(Teacher.name).all()
    courses = Course.query.filter_by(institute_id=institute_id).order_by(Course.name).all()
    classrooms = Classroom.query.filter_by(institute_id=institute_id).order_by(Classroom.name).all()
    subjects_catalog = Subject.query.filter_by(institute_id=institute_id).order_by(Subject.name).all()
    timetable = Timetable.query.filter_by(institute_id=institute_id).order_by(Timetable.day, Timetable.start_time).all()
    temporary_adjustments = (
        TemporaryTimetableAdjustment.query.filter_by(institute_id=institute_id)
        .order_by(TemporaryTimetableAdjustment.adjustment_date, TemporaryTimetableAdjustment.start_time)
        .all()
    )
    attendance = (
        Attendance.query.join(Student)
        .filter(Student.institute_id == institute_id)
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .all()
    )
    overview = build_admin_attendance_overview(students, timetable, temporary_adjustments)
    external_overview = summarize_external_attendance_for_students(students)
    if external_overview["matched_count"]:
        overview["avg_percentage"] = external_overview["avg_percentage"]
    total_attendance = external_overview["total_present"] if external_overview["matched_count"] else len(attendance)
    today_slots = [slot for slot in timetable if slot.day == today_name]
    today_adjustments = [slot for slot in temporary_adjustments if slot.adjustment_date == today]
    return {
        "students": students,
        "teachers": teachers,
        "courses": courses,
        "classrooms": classrooms,
        "subjects_catalog": subjects_catalog,
        "timetable": timetable,
        "temporary_adjustments": temporary_adjustments,
        "attendance": attendance,
        "student_attendance_rows": overview["student_rows"],
        "subject_attendance_rows": overview["subject_rows"],
        "low_attendance_rows": overview["low_attendance_rows"],
        "total_students": len(students),
        "total_teachers": len(teachers),
        "total_attendance": total_attendance,
        "avg_percentage": overview["avg_percentage"],
        "grouped_timetable": group_timetable_entries(timetable),
        "timetable_matrix": build_timetable_matrix(timetable),
        "today_slots": today_slots,
        "today_adjustments": today_adjustments,
        "today_name": today_name,
        "today_date": today,
    }


def _format_classroom_timetable_label(classroom):
    label = classroom.name
    if classroom.display_division:
        label = f"{label} ({classroom.display_division})"
    return label


def _build_classroom_timetable_sections(classrooms, timetable_entries):
    sections = []

    for classroom in classrooms:
        entries = [entry for entry in timetable_entries if entry.classroom_id == classroom.id]
        sections.append(
            {
                "id": f"classroom-{classroom.id}",
                "label": _format_classroom_timetable_label(classroom),
                "course_label": classroom.course.name if classroom.course else "-",
                "entry_count": len(entries),
                "matrix": build_timetable_matrix(entries),
            }
        )

    unassigned_entries = [entry for entry in timetable_entries if not entry.classroom_id]
    if unassigned_entries:
        sections.append(
            {
                "id": "classroom-unassigned",
                "label": "Unassigned Class Timetable",
                "course_label": "-",
                "entry_count": len(unassigned_entries),
                "matrix": build_timetable_matrix(unassigned_entries),
            }
        )

    return sections


def _validate_student_form(name, roll_number, email, password, course, require_password=True):
    if not all([name, roll_number, email, course]) or (require_password and not password):
        return "All student fields are required."
    if not _valid_name(name):
        return "Enter a valid student name."
    if not _valid_roll_number(roll_number):
        return "Roll number can contain letters, numbers, slash, underscore, and hyphen only."
    if not _valid_email(email):
        return "Enter a valid student email address."
    if not _valid_text(course, 120):
        return "Enter a valid course name."
    if password and not _valid_password(password):
        return "Student password must be at least 8 characters and include uppercase, lowercase, number, and special character."
    return None


def _validate_teacher_form(name, email, subject, password=None, require_password=True):
    if not all([name, email, subject]) or (require_password and not password):
        return "All teacher fields are required."
    if not _valid_name(name):
        return "Enter a valid teacher name."
    if not _valid_email(email):
        return "Enter a valid teacher email address."
    if not _valid_text(subject, 120):
        return "Enter a valid subject name."
    if password and not _valid_password(password):
        return "Teacher password must be at least 8 characters and include uppercase, lowercase, number, and special character."
    return None


def _find_timetable_conflict(teacher_id, day, start_time, end_time, exclude_entry_id=None):
    query = Timetable.query.filter_by(institute_id=current_user.institute_id, teacher_id=teacher_id, day=day)
    if exclude_entry_id is not None:
        query = query.filter(Timetable.id != exclude_entry_id)
    entries = query.all()
    for entry in entries:
        if start_time < entry.end_time and end_time > entry.start_time:
            return entry
    return None


def _validate_timetable_form(subject, teacher_id, day, start_time_raw, end_time_raw, course, entry_id=None):
    if not all([subject, teacher_id, day, start_time_raw, end_time_raw, course]):
        return None, None, None, "All timetable fields are required."
    if not _valid_text(subject, 120):
        return None, None, None, "Enter a valid subject name."
    if day not in ALLOWED_DAYS:
        return None, None, None, "Select a valid day."
    if not _valid_text(course, 120):
        return None, None, None, "Enter a valid course name."
    teacher = Teacher.query.filter_by(id=teacher_id, institute_id=current_user.institute_id).first()
    if not teacher:
        return None, None, None, "Select a valid teacher for this institute."
    try:
        start_time = _parse_time(start_time_raw)
        end_time = _parse_time(end_time_raw)
    except (TypeError, ValueError):
        return None, None, None, "Enter valid start and end times."
    if start_time >= end_time:
        return None, None, None, "Start time must be earlier than end time."
    conflict = _find_timetable_conflict(teacher_id, day, start_time, end_time, exclude_entry_id=entry_id)
    if conflict:
        return None, None, None, f"This teacher already has a lecture on {day} between {conflict.start_time.strftime('%I:%M %p')} and {conflict.end_time.strftime('%I:%M %p')}."
    return teacher, start_time, end_time, None


def _find_temporary_adjustment_conflict(teacher_id, adjustment_date, start_time, end_time, exclude_entry_id=None):
    query = TemporaryTimetableAdjustment.query.filter_by(
        institute_id=current_user.institute_id,
        teacher_id=teacher_id,
        adjustment_date=adjustment_date,
    )
    if exclude_entry_id is not None:
        query = query.filter(TemporaryTimetableAdjustment.id != exclude_entry_id)
    for entry in query.all():
        if start_time < entry.end_time and end_time > entry.start_time:
            return entry
    return None


def _validate_temporary_adjustment_form(subject, teacher_id, adjustment_date_raw, start_time_raw, end_time_raw, course, note=""):
    if not all([subject, teacher_id, adjustment_date_raw, start_time_raw, end_time_raw, course]):
        return None, None, None, None, "All temporary adjustment fields are required."
    if not _valid_text(subject, 120):
        return None, None, None, None, "Enter a valid subject name for the temporary adjustment."
    if not _valid_text(course, 120):
        return None, None, None, None, "Enter a valid course name for the temporary adjustment."
    if note and len(note) > 255:
        return None, None, None, None, "Temporary adjustment note must be 255 characters or fewer."
    teacher = Teacher.query.filter_by(id=teacher_id, institute_id=current_user.institute_id).first()
    if not teacher:
        return None, None, None, None, "Select a valid teacher for this temporary adjustment."
    try:
        adjustment_date = date.fromisoformat(adjustment_date_raw)
        start_time = _parse_time(start_time_raw)
        end_time = _parse_time(end_time_raw)
    except (TypeError, ValueError):
        return None, None, None, None, "Enter a valid date and time range for the temporary adjustment."
    if start_time >= end_time:
        return None, None, None, None, "Temporary adjustment start time must be earlier than end time."
    conflict = _find_temporary_adjustment_conflict(teacher_id, adjustment_date, start_time, end_time)
    if conflict:
        return None, None, None, None, f"This teacher already has a temporary adjustment on {adjustment_date.strftime('%d %b %Y')} between {conflict.start_time.strftime('%I:%M %p')} and {conflict.end_time.strftime('%I:%M %p')}."
    return teacher, adjustment_date, start_time, end_time, None


@admin_bp.get("/dashboard")
@login_required
@role_required(Role.ADMIN.value)
def dashboard():
    return render_template("admin/dashboard.html", **_admin_data(), active_page="dashboard")


@admin_bp.get("/students")
@login_required
@role_required(Role.ADMIN.value)
def manage_students():
    return render_template("admin/students.html", **_admin_data(), active_page="students")


@admin_bp.get("/teachers")
@login_required
@role_required(Role.ADMIN.value)
def manage_teachers():
    return render_template("admin/teachers.html", **_admin_data(), active_page="teachers")


@admin_bp.get("/timetable/create")
@login_required
@role_required(Role.ADMIN.value)
def create_timetable_page():
    return render_template("admin/timetable_form.html", **_admin_data(), active_page="timetable_create")


@admin_bp.get("/timetable")
@login_required
@role_required(Role.ADMIN.value)
def view_timetable():
    data = _admin_data()
    data["classroom_timetable_sections"] = _build_classroom_timetable_sections(data["classrooms"], data["timetable"])
    return render_template("admin/timetable.html", **data, active_page="timetable_view")

@admin_bp.get("/timetable/adjustments")
@login_required
@role_required(Role.ADMIN.value)
def temporary_adjustments_page():
    return render_template("admin/temporary_adjustments.html", **_admin_data(), active_page="timetable_adjustments")


@admin_bp.post("/catalog/course/create")
@login_required
@role_required(Role.ADMIN.value)
def create_course():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip().upper()
    duration_months = request.form.get("duration_months", type=int)
    validation_error = _validate_catalog_name(name, "course")
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.dashboard"))
    if code and not _valid_short_code(code):
        flash("Course code can use letters, numbers, slash, underscore, and hyphen only.", "danger")
        return redirect(url_for("admin.dashboard"))
    if duration_months is not None and duration_months <= 0:
        flash("Course duration must be greater than 0 months.", "danger")
        return redirect(url_for("admin.dashboard"))
    if Course.query.filter_by(institute_id=current_user.institute_id, name=name).first():
        flash("This course already exists.", "danger")
        return redirect(url_for("admin.dashboard"))
    try:
        db.session.add(Course(name=name, code=code or None, duration_months=duration_months, institute_id=current_user.institute_id))
        db.session.commit()
        flash("Course added successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to add course: {exc}", "danger")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/catalog/class/create")
@login_required
@role_required(Role.ADMIN.value)
def create_classroom():
    name = request.form.get("name", "").strip()
    division = request.form.get("division", "").strip().upper()
    course_id = request.form.get("course_id", type=int)
    validation_error = _validate_catalog_name(name, "class")
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.dashboard"))
    if division and not _valid_short_code(division):
        flash("Class division can use letters, numbers, slash, underscore, and hyphen only.", "danger")
        return redirect(url_for("admin.dashboard"))
    course = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    if course_id and not course:
        flash("Select a valid course for this class.", "danger")
        return redirect(url_for("admin.dashboard"))
    if Classroom.query.filter_by(institute_id=current_user.institute_id, name=name).first():
        flash("This class already exists.", "danger")
        return redirect(url_for("admin.dashboard"))
    try:
        db.session.add(Classroom(name=name, section=division or None, division=division or None, institute_id=current_user.institute_id, course_id=course.id if course else None))
        db.session.commit()
        flash("Class added successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to add class: {exc}", "danger")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/catalog/subject/create")
@login_required
@role_required(Role.ADMIN.value)
def create_subject_catalog():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip().upper()
    course_id = request.form.get("course_id", type=int)
    classroom_ids = [int(value) for value in request.form.getlist("classroom_ids") if str(value).strip()]
    validation_error = _validate_catalog_name(name, "subject")
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.dashboard"))
    if code and not _valid_short_code(code):
        flash("Subject code can use letters, numbers, slash, underscore, and hyphen only.", "danger")
        return redirect(url_for("admin.dashboard"))
    course = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    classrooms = Classroom.query.filter(Classroom.institute_id == current_user.institute_id, Classroom.id.in_(classroom_ids)).all() if classroom_ids else []
    if not course:
        flash("Select a course for this subject.", "danger")
        return redirect(url_for("admin.dashboard"))
    if not classrooms:
        flash("Select at least one class for this subject.", "danger")
        return redirect(url_for("admin.dashboard"))
    if len(classrooms) != len(set(classroom_ids)):
        flash("One or more selected classes are invalid.", "danger")
        return redirect(url_for("admin.dashboard"))
    for classroom in classrooms:
        if classroom.course_id and classroom.course_id != course.id:
            flash("Selected classes must belong to the selected course.", "danger")
            return redirect(url_for("admin.dashboard"))
    existing_subject = Subject.query.filter_by(institute_id=current_user.institute_id, name=name).first()
    try:
        if existing_subject:
            if existing_subject.course_id and existing_subject.course_id != course.id:
                flash("A subject with this name already exists under a different course.", "danger")
                return redirect(url_for("admin.dashboard"))
            existing_subject.code = code or existing_subject.code
            existing_subject.course_id = course.id
            existing_subject.classroom_id = classrooms[0].id
            existing_subject.linked_classrooms = []
            for classroom in classrooms[1:]:
                existing_subject.linked_classrooms.append(classroom)
            flash("Subject classes updated successfully.", "success")
        else:
            subject = Subject(name=name, code=code or None, institute_id=current_user.institute_id, course_id=course.id, classroom_id=classrooms[0].id)
            for classroom in classrooms[1:]:
                subject.linked_classrooms.append(classroom)
            db.session.add(subject)
            flash("Subject added successfully.", "success")
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to add subject: {exc}", "danger")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/branding/logo")
@login_required
@role_required(Role.ADMIN.value)
def upload_logo():
    logo = request.files.get("institute_logo")
    if not logo or not logo.filename:
        flash("Please choose a logo image.", "danger")
        return redirect(url_for("admin.dashboard"))

    extension = logo.filename.rsplit(".", 1)[-1].lower() if "." in logo.filename else ""
    if extension not in {"png", "jpg", "jpeg", "webp"}:
        flash("Logo must be PNG, JPG, JPEG, or WEBP.", "danger")
        return redirect(url_for("admin.dashboard"))

    for existing_ext in ("png", "jpg", "jpeg", "webp"):
        delete_if_exists(f"logos/institute_{current_user.institute_id}.{existing_ext}")

    filename = secure_filename(f"institute_{current_user.institute_id}.{extension}")
    logo_bytes = logo.read()
    if not logo_bytes:
        flash("Uploaded logo is empty.", "danger")
        return redirect(url_for("admin.dashboard"))
    save_bytes(logo_bytes, f"logos/{filename}", content_type=logo.mimetype or "application/octet-stream")
    flash("Institute logo updated.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/students/create")
@login_required
@role_required(Role.ADMIN.value)
def create_student():
    name = request.form.get("name", "").strip()
    roll_number = request.form.get("roll_number", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    course_id = request.form.get("course_id", type=int)
    classroom_id = request.form.get("classroom_id", type=int)
    course_record = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    classroom = Classroom.query.filter_by(id=classroom_id, institute_id=current_user.institute_id).first() if classroom_id else None
    if course_id and not course_record:
        flash("Select a valid course.", "danger")
        return redirect(url_for("admin.manage_students"))
    if classroom_id and not classroom:
        flash("Select a valid class.", "danger")
        return redirect(url_for("admin.manage_students"))
    if not course_record:
        flash("Select a course for the student.", "danger")
        return redirect(url_for("admin.manage_students"))
    if not classroom:
        flash("Select a class for the student.", "danger")
        return redirect(url_for("admin.manage_students"))
    if classroom and course_record and classroom.course_id and classroom.course_id != course_record.id:
        flash("Selected class does not belong to the selected course.", "danger")
        return redirect(url_for("admin.manage_students"))
    course = course_record.name
    image = request.files.get("face_image")

    validation_error = _validate_student_form(name, roll_number, email, password, course, require_password=True)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.manage_students"))
    if not image or not image.filename:
        flash("Face image is required for new students.", "danger")
        return redirect(url_for("admin.manage_students"))
    if User.query.filter_by(institute_id=current_user.institute_id, email=email).first():
        flash("A user with this email already exists in your institute.", "danger")
        return redirect(url_for("admin.manage_students"))
    if Student.query.filter_by(institute_id=current_user.institute_id, roll_number=roll_number).first():
        flash("This roll number is already registered.", "danger")
        return redirect(url_for("admin.manage_students"))

    try:
        user = User(name=name, email=email, role=Role.STUDENT.value, institute_id=current_user.institute_id, course=course, course_id=course_record.id if course_record else None)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        encoding, image_path = encode_uploaded_face(image)
        student = Student(user_id=user.id, name=name, roll_number=roll_number, email=email, course=course, course_id=course_record.id if course_record else None, classroom_id=classroom.id if classroom else None, face_encoding=encoding, face_image_path=image_path, institute_id=current_user.institute_id)
        db.session.add(student)
        db.session.commit()
        flash("Student added successfully with face profile.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to add student: {exc}", "danger")
    return redirect(url_for("admin.manage_students"))


@admin_bp.post("/students/<int:student_id>/update")
@login_required
@role_required(Role.ADMIN.value)
def update_student(student_id):
    student = Student.query.filter_by(id=student_id, institute_id=current_user.institute_id).first_or_404()
    name = request.form.get("name", student.name).strip()
    roll_number = request.form.get("roll_number", student.roll_number).strip()
    email = request.form.get("email", student.email).strip().lower()
    course_id = request.form.get("course_id", type=int)
    classroom_id = request.form.get("classroom_id", type=int)
    course_record = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    classroom = Classroom.query.filter_by(id=classroom_id, institute_id=current_user.institute_id).first() if classroom_id else None
    if course_id and not course_record:
        flash("Select a valid course.", "danger")
        return redirect(url_for("admin.manage_students"))
    if classroom_id and not classroom:
        flash("Select a valid class.", "danger")
        return redirect(url_for("admin.manage_students"))
    if not course_record:
        flash("Select a course for the student.", "danger")
        return redirect(url_for("admin.manage_students"))
    if not classroom:
        flash("Select a class for the student.", "danger")
        return redirect(url_for("admin.manage_students"))
    if classroom and course_record and classroom.course_id and classroom.course_id != course_record.id:
        flash("Selected class does not belong to the selected course.", "danger")
        return redirect(url_for("admin.manage_students"))
    course = course_record.name
    password = request.form.get("password", "")

    validation_error = _validate_student_form(name, roll_number, email, password, course, require_password=False)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.manage_students"))
    duplicate_user = User.query.filter(User.institute_id == current_user.institute_id, User.email == email, User.id != student.user_id).first()
    if duplicate_user:
        flash("Another user with this email already exists in your institute.", "danger")
        return redirect(url_for("admin.manage_students"))
    duplicate_roll = Student.query.filter(Student.institute_id == current_user.institute_id, Student.roll_number == roll_number, Student.id != student.id).first()
    if duplicate_roll:
        flash("Another student already uses this roll number.", "danger")
        return redirect(url_for("admin.manage_students"))

    try:
        student.name = name
        student.roll_number = roll_number
        student.email = email
        student.course = course
        student.course_id = course_record.id if course_record else None
        student.classroom_id = classroom.id if classroom else None
        student.user.name = name
        student.user.email = email
        student.user.course = course
        student.user.course_id = course_record.id if course_record else None
        if password:
            student.user.set_password(password)
        image = request.files.get("face_image")
        if image and image.filename:
            student.face_encoding, student.face_image_path = encode_uploaded_face(image)
        db.session.commit()
        flash("Student updated successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to update student: {exc}", "danger")
    return redirect(url_for("admin.manage_students"))


@admin_bp.post("/students/<int:student_id>/delete")
@login_required
@role_required(Role.ADMIN.value)
def delete_student(student_id):
    student = Student.query.filter_by(id=student_id, institute_id=current_user.institute_id).first_or_404()
    try:
        user = student.user
        db.session.delete(student)
        db.session.delete(user)
        db.session.commit()
        flash("Student deleted.", "info")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to delete student: {exc}", "danger")
    return redirect(url_for("admin.manage_students"))


@admin_bp.post("/teachers/create")
@login_required
@role_required(Role.ADMIN.value)
def create_teacher():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    subject_catalog_id = request.form.get("subject_catalog_id", type=int)
    course_id = request.form.get("course_id", type=int)
    subject_record = Subject.query.filter_by(id=subject_catalog_id, institute_id=current_user.institute_id).first() if subject_catalog_id else None
    course_record = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    if subject_catalog_id and not subject_record:
        flash("Select a valid subject.", "danger")
        return redirect(url_for("admin.manage_teachers"))
    if subject_record and subject_record.course_id and not course_record:
        course_record = subject_record.course
    if course_id and not course_record:
        flash("Select a valid course.", "danger")
        return redirect(url_for("admin.manage_teachers"))
    if subject_record and course_record and subject_record.course_id and subject_record.course_id != course_record.id:
        flash("Selected subject does not belong to the selected course.", "danger")
        return redirect(url_for("admin.manage_teachers"))
    subject = subject_record.name if subject_record else request.form.get("subject", "").strip()

    validation_error = _validate_teacher_form(name, email, subject, password=password, require_password=True)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.manage_teachers"))
    if User.query.filter_by(institute_id=current_user.institute_id, email=email).first():
        flash("A user with this email already exists in your institute.", "danger")
        return redirect(url_for("admin.manage_teachers"))

    try:
        user = User(name=name, email=email, role=Role.TEACHER.value, institute_id=current_user.institute_id, course=course_record.name if course_record else current_user.course, course_id=course_record.id if course_record else None)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        teacher = Teacher(user_id=user.id, name=name, email=email, subject=subject, course_id=course_record.id if course_record else None, subject_catalog_id=subject_record.id if subject_record else None, institute_id=current_user.institute_id)
        db.session.add(teacher)
        db.session.commit()
        flash("Teacher added successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to add teacher: {exc}", "danger")
    return redirect(url_for("admin.manage_teachers"))


@admin_bp.post("/teachers/<int:teacher_id>/update")
@login_required
@role_required(Role.ADMIN.value)
def update_teacher(teacher_id):
    teacher = Teacher.query.filter_by(id=teacher_id, institute_id=current_user.institute_id).first_or_404()
    name = request.form.get("name", teacher.name).strip()
    email = request.form.get("email", teacher.email).strip().lower()
    subject_catalog_id = request.form.get("subject_catalog_id", type=int)
    course_id = request.form.get("course_id", type=int)
    subject_record = Subject.query.filter_by(id=subject_catalog_id, institute_id=current_user.institute_id).first() if subject_catalog_id else None
    course_record = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    if subject_catalog_id and not subject_record:
        flash("Select a valid subject.", "danger")
        return redirect(url_for("admin.manage_teachers"))
    if subject_record and subject_record.course_id and not course_record:
        course_record = subject_record.course
    if course_id and not course_record:
        flash("Select a valid course.", "danger")
        return redirect(url_for("admin.manage_teachers"))
    if subject_record and course_record and subject_record.course_id and subject_record.course_id != course_record.id:
        flash("Selected subject does not belong to the selected course.", "danger")
        return redirect(url_for("admin.manage_teachers"))
    subject = subject_record.name if subject_record else request.form.get("subject", teacher.subject).strip()
    password = request.form.get("password", "")

    validation_error = _validate_teacher_form(name, email, subject, password=password, require_password=False)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.manage_teachers"))
    duplicate_user = User.query.filter(User.institute_id == current_user.institute_id, User.email == email, User.id != teacher.user_id).first()
    if duplicate_user:
        flash("Another user with this email already exists in your institute.", "danger")
        return redirect(url_for("admin.manage_teachers"))

    try:
        teacher.name = name
        teacher.email = email
        teacher.subject = subject
        teacher.course_id = course_record.id if course_record else None
        teacher.subject_catalog_id = subject_record.id if subject_record else None
        teacher.user.name = name
        teacher.user.email = email
        if course_record:
            teacher.user.course = course_record.name
            teacher.user.course_id = course_record.id
        if password:
            teacher.user.set_password(password)
        db.session.commit()
        flash("Teacher updated successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to update teacher: {exc}", "danger")
    return redirect(url_for("admin.manage_teachers"))


@admin_bp.post("/teachers/<int:teacher_id>/delete")
@login_required
@role_required(Role.ADMIN.value)
def delete_teacher(teacher_id):
    teacher = Teacher.query.filter_by(id=teacher_id, institute_id=current_user.institute_id).first_or_404()
    try:
        user = teacher.user
        db.session.delete(teacher)
        db.session.delete(user)
        db.session.commit()
        flash("Teacher deleted.", "info")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to delete teacher: {exc}", "danger")
    return redirect(url_for("admin.manage_teachers"))


@admin_bp.post("/timetable/create")
@login_required
@role_required(Role.ADMIN.value)
def create_timetable():
    subject_id = request.form.get("subject_id", type=int)
    course_id = request.form.get("course_id", type=int)
    classroom_id = request.form.get("classroom_id", type=int)
    subject_record = Subject.query.filter_by(id=subject_id, institute_id=current_user.institute_id).first() if subject_id else None
    course_record = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    classroom = Classroom.query.filter_by(id=classroom_id, institute_id=current_user.institute_id).first() if classroom_id else None
    if subject_id and not subject_record:
        flash("Select a valid subject.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if subject_record and subject_record.course_id and not course_record:
        course_record = subject_record.course
    if course_id and not course_record:
        flash("Select a valid course.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if classroom_id and not classroom:
        flash("Select a valid class.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if not subject_record:
        flash("Select a subject for this timetable entry.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if not course_record:
        flash("Select a course for this timetable entry.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if not classroom:
        flash("Select a class for this timetable entry.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if classroom and course_record and classroom.course_id and classroom.course_id != course_record.id:
        flash("Selected class does not belong to the selected course.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if subject_record and subject_record.course_id and subject_record.course_id != course_record.id:
        flash("Selected subject does not belong to the selected course.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if subject_record and not subject_record.applies_to_classroom(classroom.id):
        flash("Selected subject does not belong to the selected class.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    subject = subject_record.name
    teacher_id = request.form.get("teacher_id", type=int)
    day = request.form.get("day", "").strip()
    start_time_raw = request.form.get("start_time")
    end_time_raw = request.form.get("end_time")
    course = course_record.name if course_record else request.form.get("course", current_user.course).strip()
    teacher, start_time, end_time, validation_error = _validate_timetable_form(subject, teacher_id, day, start_time_raw, end_time_raw, course)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.create_timetable_page"))

    try:
        entry = Timetable(subject=subject, subject_id=subject_record.id if subject_record else None, teacher_id=teacher.id, day=day, start_time=start_time, end_time=end_time, institute_id=current_user.institute_id, course=course, course_id=course_record.id if course_record else None, classroom_id=classroom.id if classroom else None)
        db.session.add(entry)
        db.session.commit()
        flash("Timetable created.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to create timetable: {exc}", "danger")
    return redirect(url_for("admin.create_timetable_page"))


@admin_bp.post("/timetable/<int:entry_id>/update")
@login_required
@role_required(Role.ADMIN.value)
def update_timetable(entry_id):
    entry = Timetable.query.filter_by(id=entry_id, institute_id=current_user.institute_id).first_or_404()
    subject_id = request.form.get("subject_id", type=int)
    course_id = request.form.get("course_id", type=int)
    classroom_id = request.form.get("classroom_id", type=int)
    subject_record = Subject.query.filter_by(id=subject_id, institute_id=current_user.institute_id).first() if subject_id else None
    course_record = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    classroom = Classroom.query.filter_by(id=classroom_id, institute_id=current_user.institute_id).first() if classroom_id else None
    if subject_id and not subject_record:
        flash("Select a valid subject.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if subject_record and subject_record.course_id and not course_record:
        course_record = subject_record.course
    if course_id and not course_record:
        flash("Select a valid course.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if classroom_id and not classroom:
        flash("Select a valid class.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if not subject_record:
        flash("Select a subject for this timetable entry.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if not course_record:
        flash("Select a course for this timetable entry.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if not classroom:
        flash("Select a class for this timetable entry.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if classroom and course_record and classroom.course_id and classroom.course_id != course_record.id:
        flash("Selected class does not belong to the selected course.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if subject_record and subject_record.course_id and subject_record.course_id != course_record.id:
        flash("Selected subject does not belong to the selected course.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    if subject_record and not subject_record.applies_to_classroom(classroom.id):
        flash("Selected subject does not belong to the selected class.", "danger")
        return redirect(url_for("admin.create_timetable_page"))
    subject = subject_record.name
    teacher_id = request.form.get("teacher_id", type=int) or entry.teacher_id
    day = request.form.get("day", entry.day).strip()
    start_time_raw = request.form.get("start_time")
    end_time_raw = request.form.get("end_time")
    course = course_record.name if course_record else request.form.get("course", entry.course).strip()
    teacher, start_time, end_time, validation_error = _validate_timetable_form(subject, teacher_id, day, start_time_raw, end_time_raw, course, entry_id=entry.id)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.create_timetable_page"))

    try:
        entry.subject = subject
        entry.subject_id = subject_record.id if subject_record else None
        entry.teacher_id = teacher.id
        entry.day = day
        entry.start_time = start_time
        entry.end_time = end_time
        entry.course = course
        entry.course_id = course_record.id if course_record else None
        entry.classroom_id = classroom.id if classroom else None
        db.session.commit()
        flash("Timetable updated.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to update timetable: {exc}", "danger")
    return redirect(url_for("admin.create_timetable_page"))


@admin_bp.post("/timetable/<int:entry_id>/delete")
@login_required
@role_required(Role.ADMIN.value)
def delete_timetable(entry_id):
    entry = Timetable.query.filter_by(id=entry_id, institute_id=current_user.institute_id).first_or_404()
    try:
        db.session.delete(entry)
        db.session.commit()
        flash("Lecture removed from timetable.", "info")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to delete timetable entry: {exc}", "danger")
    return redirect(url_for("admin.view_timetable"))


@admin_bp.post("/timetable/temporary/create")
@login_required
@role_required(Role.ADMIN.value)
def create_temporary_adjustment():
    subject_id = request.form.get("subject_id", type=int)
    course_id = request.form.get("course_id", type=int)
    classroom_id = request.form.get("classroom_id", type=int)
    subject_record = Subject.query.filter_by(id=subject_id, institute_id=current_user.institute_id).first() if subject_id else None
    course_record = Course.query.filter_by(id=course_id, institute_id=current_user.institute_id).first() if course_id else None
    classroom = Classroom.query.filter_by(id=classroom_id, institute_id=current_user.institute_id).first() if classroom_id else None
    if subject_id and not subject_record:
        flash("Select a valid subject.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if subject_record and subject_record.course_id and not course_record:
        course_record = subject_record.course
    if course_id and not course_record:
        flash("Select a valid course.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if classroom_id and not classroom:
        flash("Select a valid class.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if not subject_record:
        flash("Select a subject for this emergency adjustment.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if not course_record:
        flash("Select a course for this emergency adjustment.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if not classroom:
        flash("Select a class for this emergency adjustment.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if classroom.course_id and classroom.course_id != course_record.id:
        flash("Selected class does not belong to the selected course.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if subject_record.course_id and subject_record.course_id != course_record.id:
        flash("Selected subject does not belong to the selected course.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    if subject_record.classroom_id and subject_record.classroom_id != classroom.id:
        flash("Selected subject does not belong to the selected class.", "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))
    subject = subject_record.name
    teacher_id = request.form.get("teacher_id", type=int)
    adjustment_date_raw = request.form.get("adjustment_date", "").strip()
    start_time_raw = request.form.get("start_time")
    end_time_raw = request.form.get("end_time")
    course = course_record.name
    note = request.form.get("note", "").strip()
    teacher, adjustment_date, start_time, end_time, validation_error = _validate_temporary_adjustment_form(
        subject,
        teacher_id,
        adjustment_date_raw,
        start_time_raw,
        end_time_raw,
        course,
        note=note,
    )
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("admin.temporary_adjustments_page"))

    try:
        entry = TemporaryTimetableAdjustment(
            subject=subject,
            subject_id=subject_record.id,
            teacher_id=teacher.id,
            adjustment_date=adjustment_date,
            start_time=start_time,
            end_time=end_time,
            institute_id=current_user.institute_id,
            course=course,
            course_id=course_record.id,
            classroom_id=classroom.id,
            note=note or None,
        )
        db.session.add(entry)
        db.session.commit()
        flash("Temporary lecture adjustment added.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to add temporary lecture adjustment: {exc}", "danger")
    return redirect(url_for("admin.temporary_adjustments_page"))


@admin_bp.post("/timetable/temporary/<int:entry_id>/delete")
@login_required
@role_required(Role.ADMIN.value)
def delete_temporary_adjustment(entry_id):
    entry = TemporaryTimetableAdjustment.query.filter_by(id=entry_id, institute_id=current_user.institute_id).first_or_404()
    try:
        db.session.delete(entry)
        db.session.commit()
        flash("Temporary lecture adjustment removed.", "info")
    except Exception as exc:
        db.session.rollback()
        flash(f"Unable to delete temporary lecture adjustment: {exc}", "danger")
    return redirect(url_for("admin.temporary_adjustments_page"))


@admin_bp.get("/attendance/export")
@login_required
@role_required(Role.ADMIN.value)
def export_attendance():
    rows = Attendance.query.join(Student).filter(Student.institute_id == current_user.institute_id).order_by(Attendance.date.desc(), Attendance.time.desc()).all()
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Student", "Roll Number", "Subject", "Date", "Time", "Status"])
    for row in rows:
        writer.writerow([row.student.name, row.student.roll_number, row.subject, row.date.isoformat(), row.time.strftime("%H:%M"), row.status])
    return Response(buffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=attendance_report.csv"})



