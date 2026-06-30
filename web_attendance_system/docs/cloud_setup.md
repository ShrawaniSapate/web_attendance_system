# Cloud Setup (Shared Across Devices)

This app can be configured to use:
- A managed PostgreSQL database so all devices share the same data
- S3-compatible object storage so uploaded files and logos are available on every device
- A network-accessible Flask host/port so the app is not limited to localhost

## 1) PostgreSQL (Managed)

Update `.env` with your hosted database details:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/attendance_system
DATABASE_SSL_MODE=require
```

Notes:
- `DATABASE_SSL_MODE=require` is common for managed PostgreSQL services.
- If your provider gives a `postgres://...` URL, the app now converts it automatically.
- Set `AUTO_CREATE_SCHEMA=true` if you want the app to create missing tables on startup.

Run `schema.sql` and `seed.py` once against the hosted database if you are starting with a fresh instance.

## 2) File Storage (S3-Compatible)

Set these values in `.env` if you want uploads and logos shared across devices:

```env
STORAGE_PROVIDER=s3
S3_BUCKET=your-bucket-name
S3_REGION=ap-south-1
S3_ENDPOINT_URL=
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
S3_PUBLIC_BASE_URL=https://your-bucket-public-url
S3_PRESIGNED_EXPIRY=3600
```

Notes:
- `S3_ENDPOINT_URL` is optional and mainly used for Cloudflare R2, MinIO, and similar providers.
- `S3_PUBLIC_BASE_URL` is optional. If you leave it empty, presigned URLs are generated.
- Keep `UPLOAD_FOLDER` for local fallback mode.

## 3) Make the App Reachable From Other Devices

Set these values in `.env`:

```env
APP_HOST=0.0.0.0
APP_PORT=5000
APP_DEBUG=false
```

Then start the app and open it from another device using your server IP, for example:

```text
http://YOUR-SERVER-IP:5000
```

For internet access outside your local network, deploy the app on a cloud VM or platform and open only the web port through your firewall or reverse proxy. Do not expose PostgreSQL directly unless you have to.

## 4) Install Dependency

```bash
pip install -r requirement.txt
```

## 5) Behavior

- `STORAGE_PROVIDER=local`: files stay on the current machine.
- `STORAGE_PROVIDER=s3`: files are shared through object storage.
- `DATABASE_URL`: points the app at either local PostgreSQL or a cloud-hosted database.
- `APP_HOST` and `APP_PORT`: control whether the web app listens only locally or on the network.
