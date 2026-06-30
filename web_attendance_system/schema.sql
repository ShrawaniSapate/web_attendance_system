CREATE TABLE institutes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    course VARCHAR(120) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    institute_id INTEGER NOT NULL REFERENCES institutes(id) ON DELETE CASCADE,
    course VARCHAR(120) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_institute_email UNIQUE (institute_id, email)
);

CREATE TABLE students (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    roll_number VARCHAR(50) NOT NULL,
    email VARCHAR(150) NOT NULL,
    course VARCHAR(120) NOT NULL,
    face_encoding TEXT,
    face_image_path VARCHAR(255),
    institute_id INTEGER NOT NULL REFERENCES institutes(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_student_roll_institute UNIQUE (institute_id, roll_number),
    CONSTRAINT uq_student_email_institute UNIQUE (institute_id, email)
);

CREATE TABLE teachers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL,
    subject VARCHAR(120) NOT NULL,
    institute_id INTEGER NOT NULL REFERENCES institutes(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_teacher_email_institute UNIQUE (institute_id, email)
);

CREATE TABLE timetable (
    id SERIAL PRIMARY KEY,
    subject VARCHAR(120) NOT NULL,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    day VARCHAR(20) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    institute_id INTEGER NOT NULL REFERENCES institutes(id) ON DELETE CASCADE,
    course VARCHAR(120) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE attendance (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    timetable_id INTEGER NOT NULL REFERENCES timetable(id) ON DELETE CASCADE,
    subject VARCHAR(120) NOT NULL,
    date DATE NOT NULL,
    time TIME NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'present',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_attendance_once_per_lecture UNIQUE (student_id, timetable_id, date)
);
