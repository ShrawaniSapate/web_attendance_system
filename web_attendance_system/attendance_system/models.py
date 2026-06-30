from datetime import datetime, time
from enum import Enum

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db



subject_classrooms = db.Table(
    "subject_classrooms",
    db.Column("subject_id", db.Integer, db.ForeignKey("subjects_catalog.id"), primary_key=True),
    db.Column("classroom_id", db.Integer, db.ForeignKey("classrooms.id"), primary_key=True),
)


class Role(str, Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class Institute(db.Model):
    __tablename__ = "institutes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    users = db.relationship("User", back_populates="institute", cascade="all, delete-orphan")
    students = db.relationship("Student", back_populates="institute", cascade="all, delete-orphan")
    teachers = db.relationship("Teacher", back_populates="institute", cascade="all, delete-orphan")
    courses = db.relationship("Course", back_populates="institute", cascade="all, delete-orphan")
    classrooms = db.relationship("Classroom", back_populates="institute", cascade="all, delete-orphan")
    subjects_catalog = db.relationship("Subject", back_populates="institute", cascade="all, delete-orphan")
    timetable_entries = db.relationship("Timetable", back_populates="institute", cascade="all, delete-orphan")
    temporary_adjustments = db.relationship("TemporaryTimetableAdjustment", back_populates="institute", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("institute_id", "email", name="uq_user_institute_email"),)

    institute = db.relationship("Institute", back_populates="users")
    course_record = db.relationship("Course", back_populates="users")
    student_profile = db.relationship("Student", back_populates="user", uselist=False)
    teacher_profile = db.relationship("Teacher", back_populates="user", uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    roll_number = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=True)
    face_encoding = db.Column(db.Text, nullable=True)
    face_image_path = db.Column(db.String(255), nullable=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("institute_id", "roll_number", name="uq_student_roll_institute"),
        db.UniqueConstraint("institute_id", "email", name="uq_student_email_institute"),
    )

    user = db.relationship("User", back_populates="student_profile")
    institute = db.relationship("Institute", back_populates="students")
    course_record = db.relationship("Course", back_populates="students")
    classroom = db.relationship("Classroom", back_populates="students")
    attendance_records = db.relationship("Attendance", back_populates="student", cascade="all, delete-orphan")


class Teacher(db.Model):
    __tablename__ = "teachers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    subject_catalog_id = db.Column(db.Integer, db.ForeignKey("subjects_catalog.id"), nullable=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("institute_id", "email", name="uq_teacher_email_institute"),)

    user = db.relationship("User", back_populates="teacher_profile")
    institute = db.relationship("Institute", back_populates="teachers")
    course_record = db.relationship("Course", back_populates="teachers")
    subject_record = db.relationship("Subject", back_populates="teachers")
    timetable_entries = db.relationship("Timetable", back_populates="teacher", cascade="all, delete-orphan")
    temporary_adjustments = db.relationship("TemporaryTimetableAdjustment", back_populates="teacher", cascade="all, delete-orphan")


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(30), nullable=True)
    duration_months = db.Column(db.Integer, nullable=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("institute_id", "name", name="uq_course_institute_name"),)

    institute = db.relationship("Institute", back_populates="courses")
    users = db.relationship("User", back_populates="course_record")
    students = db.relationship("Student", back_populates="course_record")
    teachers = db.relationship("Teacher", back_populates="course_record")
    classrooms = db.relationship("Classroom", back_populates="course")
    subjects = db.relationship("Subject", back_populates="course")
    timetable_entries = db.relationship("Timetable", back_populates="course_record")
    temporary_adjustments = db.relationship("TemporaryTimetableAdjustment", back_populates="course_record")


class Classroom(db.Model):
    __tablename__ = "classrooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    section = db.Column(db.String(30), nullable=True)
    division = db.Column(db.String(30), nullable=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("institute_id", "name", name="uq_classroom_institute_name"),)

    institute = db.relationship("Institute", back_populates="classrooms")
    course = db.relationship("Course", back_populates="classrooms")
    students = db.relationship("Student", back_populates="classroom")
    subjects = db.relationship("Subject", back_populates="classroom")
    linked_subjects = db.relationship("Subject", secondary=subject_classrooms, back_populates="linked_classrooms")
    timetable_entries = db.relationship("Timetable", back_populates="classroom")
    temporary_adjustments = db.relationship("TemporaryTimetableAdjustment", back_populates="classroom")

    @property
    def display_division(self):
        return self.division or self.section


class Subject(db.Model):
    __tablename__ = "subjects_catalog"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(30), nullable=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("institute_id", "name", name="uq_subject_institute_name"),)

    institute = db.relationship("Institute", back_populates="subjects_catalog")
    course = db.relationship("Course", back_populates="subjects")
    classroom = db.relationship("Classroom", back_populates="subjects")
    teachers = db.relationship("Teacher", back_populates="subject_record")
    timetable_entries = db.relationship("Timetable", back_populates="subject_record")
    temporary_adjustments = db.relationship("TemporaryTimetableAdjustment", back_populates="subject_record")
    linked_classrooms = db.relationship("Classroom", secondary=subject_classrooms, back_populates="linked_subjects")

    def applies_to_classroom(self, classroom_id):
        if not classroom_id:
            return True
        if self.classroom_id == classroom_id:
            return True
        return any(classroom.id == classroom_id for classroom in self.linked_classrooms)

    @property
    def all_classrooms(self):
        classrooms = []
        if self.classroom is not None:
            classrooms.append(self.classroom)
        for classroom in self.linked_classrooms:
            if all(existing.id != classroom.id for existing in classrooms):
                classrooms.append(classroom)
        return classrooms


class Timetable(db.Model):
    __tablename__ = "timetable"

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(120), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects_catalog.id"), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False)
    day = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    teacher = db.relationship("Teacher", back_populates="timetable_entries")
    institute = db.relationship("Institute", back_populates="timetable_entries")
    subject_record = db.relationship("Subject", back_populates="timetable_entries")
    course_record = db.relationship("Course", back_populates="timetable_entries")
    classroom = db.relationship("Classroom", back_populates="timetable_entries")
    attendance_records = db.relationship("Attendance", back_populates="timetable_entry", cascade="all, delete-orphan")

    @property
    def slot_ref(self):
        return f"timetable-{self.id}"

    @property
    def slot_kind(self):
        return "weekly"

    def is_live(self, current_day: str, current_time: time):
        return self.day.lower() == current_day.lower() and self.start_time <= current_time <= self.end_time


class TemporaryTimetableAdjustment(db.Model):
    __tablename__ = "temporary_timetable_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(120), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects_catalog.id"), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False)
    adjustment_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=True)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    teacher = db.relationship("Teacher", back_populates="temporary_adjustments")
    institute = db.relationship("Institute", back_populates="temporary_adjustments")
    subject_record = db.relationship("Subject", back_populates="temporary_adjustments")
    course_record = db.relationship("Course", back_populates="temporary_adjustments")
    classroom = db.relationship("Classroom", back_populates="temporary_adjustments")
    attendance_records = db.relationship("Attendance", back_populates="temporary_adjustment")

    @property
    def day(self):
        return self.adjustment_date.strftime("%A")

    @property
    def slot_ref(self):
        return f"temporary-{self.id}"

    @property
    def slot_kind(self):
        return "emergency"

    def is_live(self, current_day: str, current_time: time, current_date=None):
        if current_date is not None and current_date != self.adjustment_date:
            return False
        return self.day.lower() == current_day.lower() and self.start_time <= current_time <= self.end_time


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    timetable_id = db.Column(db.Integer, db.ForeignKey("timetable.id"), nullable=True)
    temporary_adjustment_id = db.Column(db.Integer, db.ForeignKey("temporary_timetable_adjustments.id"), nullable=True)
    subject = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), default="present", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("student_id", "timetable_id", "date", name="uq_attendance_once_per_lecture"),
        db.UniqueConstraint("student_id", "temporary_adjustment_id", "date", name="uq_attendance_once_per_temporary_adjustment"),
    )

    student = db.relationship("Student", back_populates="attendance_records")
    timetable_entry = db.relationship("Timetable", back_populates="attendance_records")
    temporary_adjustment = db.relationship("TemporaryTimetableAdjustment", back_populates="attendance_records")

