import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from attendance_system.extensions import db
from attendance_system.models import Institute, Role, User
from attendance_system.services.auth_service import authenticate_user


auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z\s.'-]{1,99}$")
ROLL_RE = re.compile(r"^[A-Za-z0-9/_-]{2,30}$")
TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\s&().,'/-]{1,119}$")


ROLE_META = {
    Role.ADMIN.value: {
        "title": "Admin Login",
        "button": "Login as Admin",
        "badge": "Administrator",
        "subtitle": "Use institute credentials to access the admin control center.",
    },
    Role.TEACHER.value: {
        "title": "Teacher Login",
        "button": "Login as Teacher",
        "badge": "Faculty",
        "subtitle": "Login with your teacher name, email, and password.",
    },
    Role.STUDENT.value: {
        "title": "Student Login",
        "button": "Login as Student",
        "badge": "Learner",
        "subtitle": "Login with your student name, roll number, and password.",
    },
}


def _valid_email(email: str) -> bool:
    return bool(EMAIL_RE.fullmatch(email or ""))


def _valid_name(value: str) -> bool:
    return bool(NAME_RE.fullmatch(value or ""))


def _valid_roll_number(value: str) -> bool:
    return bool(ROLL_RE.fullmatch(value or ""))


def _valid_text(value: str, max_length: int = 120) -> bool:
    return bool(value) and len(value) <= max_length and bool(TEXT_RE.fullmatch(value))


def _valid_password(password: str) -> bool:
    if len(password or "") < 8:
        return False
    checks = [
        re.search(r"[A-Z]", password),
        re.search(r"[a-z]", password),
        re.search(r"\d", password),
        re.search(r"[^A-Za-z0-9]", password),
    ]
    return all(checks)


def _validate_login_form(role, form_data):
    password = form_data.get("password", "")
    if not password:
        return "Password is required."

    if role == Role.ADMIN.value:
        institute_name = form_data.get("institute_name", "").strip()
        email = form_data.get("email", "").strip().lower()
        if not all([institute_name, email, password]):
            return "All login fields are required."
        if not _valid_text(institute_name, 120):
            return "Enter a valid institute name."
        if not _valid_email(email):
            return "Enter a valid email address."
        return None

    if role == Role.TEACHER.value:
        name = form_data.get("name", "").strip()
        email = form_data.get("email", "").strip().lower()
        if not all([name, email, password]):
            return "All login fields are required."
        if not _valid_name(name):
            return "Enter a valid teacher name."
        if not _valid_email(email):
            return "Enter a valid email address."
        return None

    if role == Role.STUDENT.value:
        name = form_data.get("name", "").strip()
        roll_number = form_data.get("roll_number", "").strip()
        if not all([name, roll_number, password]):
            return "All login fields are required."
        if not _valid_name(name):
            return "Enter a valid student name."
        if not _valid_roll_number(roll_number):
            return "Enter a valid roll number."
        return None

    return "Invalid login role selected."


@auth_bp.get("/")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard_redirect"))
    return render_template("auth/login_selector.html", role_meta=ROLE_META)


@auth_bp.get("/login/<role>")
def role_login_page(role):
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard_redirect"))
    if role not in ROLE_META:
        flash("Invalid login role selected.", "danger")
        return redirect(url_for("auth.login_page"))
    return render_template("auth/role_login.html", role=role, role_meta=ROLE_META[role])


@auth_bp.post("/login/<role>")
def role_login(role):
    if role not in ROLE_META:
        flash("Invalid login role selected.", "danger")
        return redirect(url_for("auth.login_page"))

    validation_error = _validate_login_form(role, request.form)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("auth.role_login_page", role=role))

    user, error = authenticate_user(role, request.form)
    if error:
        flash(error, "danger")
        return redirect(url_for("auth.role_login_page", role=role))

    login_user(user)
    flash("Login successful.", "success")
    return redirect(url_for("main.dashboard_redirect"))


@auth_bp.get("/register")
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard_redirect"))
    return render_template("auth/register.html")


@auth_bp.post("/register")
def register():
    name = request.form.get("institute_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not all([name, email, password]):
        flash("All fields are required.", "danger")
        return redirect(url_for("auth.register_page"))

    if not _valid_text(name, 120):
        flash("Enter a valid institute name.", "danger")
        return redirect(url_for("auth.register_page"))

    if not _valid_email(email):
        flash("Enter a valid institute email address.", "danger")
        return redirect(url_for("auth.register_page"))

    if not _valid_password(password):
        flash("Password must be at least 8 characters and include uppercase, lowercase, number, and special character.", "danger")
        return redirect(url_for("auth.register_page"))

    if Institute.query.filter((Institute.name.ilike(name)) | (Institute.email == email)).first():
        flash("Institute already registered with this name or email.", "danger")
        return redirect(url_for("auth.register_page"))

    institute = Institute(name=name, email=email, course="General")
    institute.set_password(password)
    db.session.add(institute)
    db.session.flush()

    admin_user = User(
        name=f"{name} Admin",
        email=email,
        role=Role.ADMIN.value,
        institute_id=institute.id,
        course="General",
    )
    admin_user.set_password(password)
    db.session.add(admin_user)
    db.session.commit()

    flash("Institute registered successfully. Please log in as admin.", "success")
    return redirect(url_for("auth.role_login_page", role=Role.ADMIN.value))


@auth_bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login_page"))
