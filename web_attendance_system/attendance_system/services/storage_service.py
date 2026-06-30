import os
from functools import lru_cache
from pathlib import Path

from flask import current_app, has_app_context, url_for

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None


ALLOWED_LOGO_EXTENSIONS = ("png", "jpg", "jpeg", "webp")


def _config_get(key, default=None, app=None):
    if app is not None:
        return app.config.get(key, default)
    if has_app_context():
        return current_app.config.get(key, default)
    return default


def _storage_provider(app=None):
    return (_config_get("STORAGE_PROVIDER", "local", app=app) or "local").lower()


def is_s3_enabled(app=None):
    return (
        _storage_provider(app=app) == "s3"
        and bool(_config_get("S3_BUCKET", "", app=app))
        and boto3 is not None
    )


@lru_cache(maxsize=1)
def _cached_s3_client(cache_key):
    _, endpoint_url, region, key_id, secret = cache_key
    kwargs = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if region:
        kwargs["region_name"] = region
    if key_id and secret:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("s3", **kwargs)


def _s3_client(app=None):
    cache_key = (
        _config_get("S3_BUCKET", "", app=app),
        _config_get("S3_ENDPOINT_URL", "", app=app),
        _config_get("S3_REGION", "", app=app),
        _config_get("S3_ACCESS_KEY_ID", "", app=app),
        _config_get("S3_SECRET_ACCESS_KEY", "", app=app),
    )
    return _cached_s3_client(cache_key)


def _local_abspath(storage_key: str):
    normalized_key = storage_key
    if normalized_key.startswith("uploads/"):
        normalized_key = normalized_key[len("uploads/") :]
    return os.path.join(current_app.config["UPLOAD_FOLDER"], normalized_key.replace("/", os.sep))


def ensure_storage_dirs(app=None):
    if is_s3_enabled(app=app):
        return
    upload_folder = _config_get("UPLOAD_FOLDER", "", app=app)
    os.makedirs(upload_folder, exist_ok=True)
    os.makedirs(os.path.join(upload_folder, "logos"), exist_ok=True)


def delete_if_exists(storage_key: str):
    if not storage_key:
        return
    if is_s3_enabled():
        _s3_client().delete_object(Bucket=current_app.config["S3_BUCKET"], Key=storage_key)
        return
    local_path = _local_abspath(storage_key)
    if os.path.exists(local_path):
        os.remove(local_path)


def save_bytes(content: bytes, storage_key: str, content_type: str | None = None):
    if is_s3_enabled():
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        _s3_client().put_object(
            Bucket=current_app.config["S3_BUCKET"],
            Key=storage_key,
            Body=content,
            **extra_args,
        )
        return storage_key

    local_path = _local_abspath(storage_key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as handle:
        handle.write(content)
    return storage_key


def build_storage_url(storage_key: str):
    if not storage_key:
        return None

    if is_s3_enabled():
        public_base = current_app.config.get("S3_PUBLIC_BASE_URL")
        if public_base:
            return f"{public_base}/{storage_key}"
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": current_app.config["S3_BUCKET"], "Key": storage_key},
            ExpiresIn=int(current_app.config.get("S3_PRESIGNED_EXPIRY", 3600)),
        )

    static_key = storage_key if storage_key.startswith("uploads/") else f"uploads/{storage_key}"
    return url_for("static", filename=static_key)


def resolve_institute_logo_url(institute_id: int | None):
    if not institute_id:
        return None

    if is_s3_enabled():
        for extension in ALLOWED_LOGO_EXTENSIONS:
            key = f"logos/institute_{int(institute_id)}.{extension}"
            try:
                _s3_client().head_object(Bucket=current_app.config["S3_BUCKET"], Key=key)
                return build_storage_url(key)
            except Exception:
                continue
        return None

    logo_dir = Path(current_app.config["UPLOAD_FOLDER"]) / "logos"
    for extension in ALLOWED_LOGO_EXTENSIONS:
        candidate = logo_dir / f"institute_{int(institute_id)}.{extension}"
        if candidate.exists():
            return url_for("static", filename=f"uploads/logos/{candidate.name}")
    return None