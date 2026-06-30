from attendance_system.models import Institute, Student, Teacher, User


def authenticate_user(role, form_data):
    password = form_data.get("password", "")

    if role == "admin":
        institute_name = form_data.get("institute_name", "")
        email = form_data.get("email", "")

        institute = Institute.query.filter(Institute.name.ilike(institute_name.strip())).first()
        if not institute:
            return None, "Institute not found."

        user = User.query.filter_by(
            institute_id=institute.id,
            email=email.strip().lower(),
            role="admin",
        ).first()

        if not user or not user.check_password(password):
            return None, "Invalid admin credentials."
        return user, None

    if role == "teacher":
        name = form_data.get("name", "").strip()
        email = form_data.get("email", "").strip().lower()
        teacher = Teacher.query.filter(Teacher.name.ilike(name), Teacher.email == email).first()
        if not teacher:
            return None, "Teacher not found."
        if not teacher.user or not teacher.user.check_password(password):
            return None, "Invalid teacher credentials."
        return teacher.user, None

    if role == "student":
        name = form_data.get("name", "").strip()
        roll_number = form_data.get("roll_number", "").strip()
        student = Student.query.filter(Student.name.ilike(name), Student.roll_number == roll_number).first()
        if not student:
            return None, "Student not found."
        if not student.user or not student.user.check_password(password):
            return None, "Invalid student credentials."
        return student.user, None

    return None, "Invalid login role selected."
