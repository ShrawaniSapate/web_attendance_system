import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv


load_dotenv()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_UPLOAD_FOLDER = os.path.join(BASE_DIR, "attendance_system", "static", "uploads")


def _normalize_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        return "postgresql+psycopg2://postgres:postgres@localhost:5432/attendance_system"

    if url.startswith("postgres://"):
        url = f"postgresql://{url[len('postgres://') :]}"

    if url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))

    ssl_mode = os.getenv("DATABASE_SSL_MODE", "").strip()
    if ssl_mode:
        query.setdefault("sslmode", ssl_mode)

    is_neon_pooler = "-pooler." in (parts.hostname or "")
    if not is_neon_pooler:
        # Direct Neon/local connections can use an explicit search_path.
        query.setdefault("options", "-csearch_path=public")

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv("DATABASE_URL", ""))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", DEFAULT_UPLOAD_FOLDER)
    STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "local").strip().lower()
    S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
    S3_REGION = os.getenv("S3_REGION", "").strip()
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "").strip()
    S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "").strip()
    S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
    S3_PUBLIC_BASE_URL = os.getenv("S3_PUBLIC_BASE_URL", "").strip().rstrip("/")
    S3_PRESIGNED_EXPIRY = int(os.getenv("S3_PRESIGNED_EXPIRY", "3600"))
    AUTO_CREATE_SCHEMA = os.getenv("AUTO_CREATE_SCHEMA", "true").strip().lower() in {"1", "true", "yes", "on"}
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0").strip() or "0.0.0.0"
    APP_PORT = int(os.getenv("APP_PORT", "5000"))
    APP_DEBUG = os.getenv("APP_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
    EXTERNAL_ATTENDANCE_XLSX = os.getenv("EXTERNAL_ATTENDANCE_XLSX", r"C:\Users\KUMAR NAGAWADE\Downloads\attendance_with_dates.xlsx").strip()
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024


