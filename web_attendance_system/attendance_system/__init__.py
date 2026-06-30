from flask import Flask
from sqlalchemy import inspect, text

from .config import Config
from .extensions import db, login_manager
from .models import User
from .services.storage_service import ensure_storage_dirs, resolve_institute_logo_url

SUBJECT_THEME_CLASSES = [
    "subject-theme-1",
    "subject-theme-2",
    "subject-theme-3",
    "subject-theme-4",
    "subject-theme-5",
    "subject-theme-6",
]


def _ensure_attendance_schema_supports_adjustments():
    inspector = inspect(db.engine)
    attendance_columns = {column["name"]: column for column in inspector.get_columns("attendance")}

    with db.engine.begin() as connection:
        if "temporary_adjustment_id" not in attendance_columns:
            connection.execute(text("ALTER TABLE attendance ADD COLUMN temporary_adjustment_id INTEGER"))
            connection.execute(
                text(
                    "ALTER TABLE attendance ADD CONSTRAINT attendance_temporary_adjustment_id_fkey "
                    "FOREIGN KEY (temporary_adjustment_id) REFERENCES temporary_timetable_adjustments (id)"
                )
            )

        timetable_column = attendance_columns.get("timetable_id")
        if timetable_column and not timetable_column.get("nullable", True):
            connection.execute(text("ALTER TABLE attendance ALTER COLUMN timetable_id DROP NOT NULL"))

        existing_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("attendance")}
        if "uq_attendance_once_per_temporary_adjustment" not in existing_constraints:
            connection.execute(
                text(
                    "ALTER TABLE attendance ADD CONSTRAINT uq_attendance_once_per_temporary_adjustment "
                    "UNIQUE (student_id, temporary_adjustment_id, date)"
                )
            )




def _ensure_column(connection, inspector, table_name, column_name, column_sql, fk_name=None, fk_target=None):
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in columns:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))
    if fk_name and fk_target:
        foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys(table_name)}
        if fk_name not in foreign_keys:
            connection.execute(text(
                f"ALTER TABLE {table_name} ADD CONSTRAINT {fk_name} FOREIGN KEY ({column_name}) REFERENCES {fk_target}"
            ))


def _ensure_catalog_relationship_schema():
    inspector = inspect(db.engine)
    with db.engine.begin() as connection:
        _ensure_column(connection, inspector, "courses", "duration_months", "INTEGER")
        _ensure_column(connection, inspector, "classrooms", "division", "VARCHAR(30)")
        _ensure_column(connection, inspector, "users", "course_id", "INTEGER", "users_course_id_fkey", "courses (id)")
        _ensure_column(connection, inspector, "students", "course_id", "INTEGER", "students_course_id_fkey", "courses (id)")
        _ensure_column(connection, inspector, "students", "classroom_id", "INTEGER", "students_classroom_id_fkey", "classrooms (id)")
        _ensure_column(connection, inspector, "teachers", "course_id", "INTEGER", "teachers_course_id_fkey", "courses (id)")
        _ensure_column(connection, inspector, "teachers", "subject_catalog_id", "INTEGER", "teachers_subject_catalog_id_fkey", "subjects_catalog (id)")
        _ensure_column(connection, inspector, "timetable", "subject_id", "INTEGER", "timetable_subject_id_fkey", "subjects_catalog (id)")
        _ensure_column(connection, inspector, "timetable", "course_id", "INTEGER", "timetable_course_id_fkey", "courses (id)")
        _ensure_column(connection, inspector, "timetable", "classroom_id", "INTEGER", "timetable_classroom_id_fkey", "classrooms (id)")
        _ensure_column(connection, inspector, "temporary_timetable_adjustments", "subject_id", "INTEGER", "temporary_adjustments_subject_id_fkey", "subjects_catalog (id)")
        _ensure_column(connection, inspector, "temporary_timetable_adjustments", "course_id", "INTEGER", "temporary_adjustments_course_id_fkey", "courses (id)")
        _ensure_column(connection, inspector, "temporary_timetable_adjustments", "classroom_id", "INTEGER", "temporary_adjustments_classroom_id_fkey", "classrooms (id)")

        connection.execute(text("UPDATE classrooms SET division = section WHERE division IS NULL AND section IS NOT NULL"))
        connection.execute(text("UPDATE users u SET course_id = c.id FROM courses c WHERE u.course_id IS NULL AND u.institute_id = c.institute_id AND u.course = c.name"))
        connection.execute(text("UPDATE students s SET course_id = c.id FROM courses c WHERE s.course_id IS NULL AND s.institute_id = c.institute_id AND s.course = c.name"))
        connection.execute(text("UPDATE teachers t SET course_id = c.id FROM courses c WHERE t.course_id IS NULL AND t.institute_id = c.institute_id AND c.name = (SELECT u.course FROM users u WHERE u.id = t.user_id)"))
        connection.execute(text("UPDATE teachers t SET subject_catalog_id = sc.id FROM subjects_catalog sc WHERE t.subject_catalog_id IS NULL AND t.institute_id = sc.institute_id AND t.subject = sc.name"))
        connection.execute(text("UPDATE timetable tt SET course_id = c.id FROM courses c WHERE tt.course_id IS NULL AND tt.institute_id = c.institute_id AND tt.course = c.name"))
        connection.execute(text("UPDATE timetable tt SET subject_id = sc.id FROM subjects_catalog sc WHERE tt.subject_id IS NULL AND tt.institute_id = sc.institute_id AND tt.subject = sc.name"))
        connection.execute(text("UPDATE temporary_timetable_adjustments ta SET course_id = c.id FROM courses c WHERE ta.course_id IS NULL AND ta.institute_id = c.institute_id AND ta.course = c.name"))
        connection.execute(text("UPDATE temporary_timetable_adjustments ta SET subject_id = sc.id FROM subjects_catalog sc WHERE ta.subject_id IS NULL AND ta.institute_id = sc.institute_id AND ta.subject = sc.name"))


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    ensure_storage_dirs(app)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login_page"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_branding_helpers():
        def institute_logo_url(institute_id=None):
            target_institute_id = institute_id
            if target_institute_id is None:
                from flask_login import current_user

                if current_user.is_authenticated:
                    target_institute_id = current_user.institute_id
            if not target_institute_id:
                return None

            return resolve_institute_logo_url(int(target_institute_id))

        def subject_theme(value):
            if not value:
                return SUBJECT_THEME_CLASSES[0]
            index = sum(ord(ch) for ch in str(value)) % len(SUBJECT_THEME_CLASSES)
            return SUBJECT_THEME_CLASSES[index]

        return {
            "institute_logo_url": institute_logo_url,
            "subject_theme": subject_theme,
        }

    from .routes.admin import admin_bp
    from .routes.api import api_bp
    from .routes.auth import auth_bp
    from .routes.main import main_bp
    from .routes.student import student_bp
    from .routes.teacher import teacher_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    if app.config["AUTO_CREATE_SCHEMA"]:
        with app.app_context():
            db.create_all()
            _ensure_attendance_schema_supports_adjustments()
            _ensure_catalog_relationship_schema()

    return app
