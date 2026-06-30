from functools import wraps

from flask import abort
from flask_login import current_user

from attendance_system.models import Role


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def is_admin():
    return current_user.is_authenticated and current_user.role == Role.ADMIN.value
