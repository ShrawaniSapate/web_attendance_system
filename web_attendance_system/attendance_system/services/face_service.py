import base64
import json
import mimetypes
import uuid

import numpy as np
from werkzeug.utils import secure_filename

from attendance_system.services.storage_service import save_bytes

try:
    import cv2
    import face_recognition
except ImportError:  # pragma: no cover
    cv2 = None
    face_recognition = None


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}


def _ensure_libs():
    if cv2 is None or face_recognition is None:
        raise RuntimeError("OpenCV and face_recognition must be installed to use face features.")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def encode_uploaded_face(file_storage):
    _ensure_libs()

    if not file_storage or not allowed_file(file_storage.filename):
        raise ValueError("Please upload a valid JPG or PNG face image.")

    image_bytes = file_storage.read()
    if not image_bytes:
        raise ValueError("Uploaded image is empty.")

    np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise ValueError("Uploaded image could not be decoded.")
    image = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    encodings = face_recognition.face_encodings(image)
    if not encodings:
        raise ValueError("No face detected in uploaded image.")

    unique_name = f"{uuid.uuid4().hex}_{secure_filename(file_storage.filename)}"
    storage_key = f"uploads/{unique_name}"
    content_type = file_storage.mimetype or mimetypes.guess_type(file_storage.filename)[0] or "application/octet-stream"
    save_bytes(image_bytes, storage_key, content_type=content_type)

    return json.dumps(encodings[0].tolist()), storage_key


def _decode_frame(frame_b64):
    _ensure_libs()

    if "," in frame_b64:
        frame_b64 = frame_b64.split(",", 1)[1]

    data = base64.b64decode(frame_b64)
    np_arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)


def identify_students(frame_b64, students, tolerance=0.45):
    _ensure_libs()

    frame = _decode_frame(frame_b64)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb)
    live_encodings = face_recognition.face_encodings(rgb, face_locations)
    if not live_encodings:
        return []

    known_students = []
    for student in students:
        if not student.face_encoding:
            continue
        known_students.append(
            {
                "student": student,
                "encoding": np.array(json.loads(student.face_encoding)),
            }
        )

    matches = []
    matched_student_ids = set()

    for location, live_encoding in zip(face_locations, live_encodings):
        best_match = None
        normalized_location = {
            "top": int(location[0]),
            "right": int(location[1]),
            "bottom": int(location[2]),
            "left": int(location[3]),
        }
        for known in known_students:
            student = known["student"]
            if student.id in matched_student_ids:
                continue

            distance = float(face_recognition.face_distance([known["encoding"]], live_encoding)[0])
            if distance <= tolerance and (best_match is None or distance < best_match["distance"]):
                best_match = {
                    "student": student,
                    "distance": distance,
                    "location": normalized_location,
                    "matched": True,
                }

        if best_match is not None:
            matches.append(best_match)
            matched_student_ids.add(best_match["student"].id)
        else:
            matches.append(
                {
                    "student": None,
                    "distance": None,
                    "location": normalized_location,
                    "matched": False,
                }
            )

    return matches
