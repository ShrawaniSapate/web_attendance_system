import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from attendance_system import create_app
from attendance_system.extensions import db
from attendance_system.models import Attendance, Institute, Role, Student, Teacher, Timetable, User



app = create_app()


def seed():
    with app.app_context():
        if Institute.query.filter_by(email="admin@demo.edu").first():
            print("Seed data already exists.")
            return

        institute = Institute(
            name="Demo Global Institute",
            email="admin@demo.edu",
            course="BSc Computer Science",
        )
        institute.set_password("Admin@123")
        db.session.add(institute)
        db.session.flush()

        admin = User(
            name="Demo Admin",
            email="admin@demo.edu",
            role=Role.ADMIN.value,
            institute_id=institute.id,
            course=institute.course,
        )
        admin.set_password("Admin@123")

        teacher_user = User(
            name="Meera Singh",
            email="teacher@demo.edu",
            role=Role.TEACHER.value,
            institute_id=institute.id,
            course=institute.course,
        )
        teacher_user.set_password("Teacher@123")

        student_user = User(
            name="Aarav Sharma",
            email="student@demo.edu",
            role=Role.STUDENT.value,
            institute_id=institute.id,
            course=institute.course,
        )
        student_user.set_password("Student@123")

        db.session.add_all([admin, teacher_user, student_user])
        db.session.flush()

        teacher = Teacher(
            user_id=teacher_user.id,
            name="Meera Singh",
            email="teacher@demo.edu",
            subject="Artificial Intelligence",
            institute_id=institute.id,
        )

        student = Student(
            user_id=student_user.id,
            name="Aarav Sharma",
            roll_number="CS001",
            email="student@demo.edu",
            course=institute.course,
            institute_id=institute.id,
        )

        db.session.add_all([teacher, student])
        db.session.flush()

        slot = Timetable(
            subject="Artificial Intelligence",
            teacher_id=teacher.id,
            day="Thursday",
            start_time=time(9, 0),
            end_time=time(10, 0),
            institute_id=institute.id,
            course=institute.course,
        )
        db.session.add(slot)
        db.session.flush()

        attendance = Attendance(
            student_id=student.id,
            timetable_id=slot.id,
            subject=slot.subject,
            date=date.today(),
            time=time(9, 5),
            status="present",
        )
        db.session.add(attendance)
        db.session.commit()

        print("Seed data inserted successfully.")


if __name__ == "__main__":
    seed()
