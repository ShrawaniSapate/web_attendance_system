from flask import Blueprint, redirect, url_for
from flask_login import current_user, login_required

from attendance_system.models import Role


main_bp = Blueprint("main", __name__)


@main_bp.get("/dashboard")
@login_required
def dashboard_redirect():
    if current_user.role == Role.ADMIN.value:
        return redirect(url_for("admin.dashboard"))
    if current_user.role == Role.TEACHER.value:
        return redirect(url_for("teacher.dashboard"))
    return redirect(url_for("student.dashboard"))
