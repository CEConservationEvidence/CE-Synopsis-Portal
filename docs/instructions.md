## Pilot Setup

Public URLs:
- app: `http://<server-ip>:8000`
- ONLYOFFICE: `http://<server-ip>:8080`

For this simple onine pilot, email should send only to internal test inboxes.

## Values needed

Admin to provide:
- server IP
- Django `SECRET_KEY`
- PostgreSQL password
- ONLYOFFICE JWT secret
- SMTP host
- SMTP port
- SMTP user
- SMTP password
- sender mailbox for the pilot

## `.env` configuration

Start from:

```bash
cp .env.template .env
```

Set at least:

```env
SECRET_KEY=<django-secret>

DB_NAME=ce_portal
DB_USER=ce_user
DB_PASSWORD=<db-password>

WEB_BIND_HOST=0.0.0.0
WEB_PORT=8000
ONLYOFFICE_BIND_HOST=0.0.0.0
ONLYOFFICE_PORT=8080

ALLOWED_HOSTS=<server-ip>
CSRF_TRUSTED_ORIGINS=http://<server-ip>:8000

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<smtp-host>
EMAIL_PORT=587
EMAIL_HOST_USER=<smtp-user>
EMAIL_HOST_PASSWORD=<smtp-password>
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=CE Synopsis Pilot <pilot-mailbox@your-organisation>
SERVER_EMAIL=CE Synopsis Pilot <pilot-mailbox@your-organisation>

ONLYOFFICE_URL=http://<server-ip>:8080
ONLYOFFICE_INTERNAL_URL=http://onlyoffice
ONLYOFFICE_APP_BASE_URL=http://<server-ip>:8000
ONLYOFFICE_JWT_ENABLED=true
ONLYOFFICE_JWT_SECRET=<onlyoffice-jwt-secret>
ONLYOFFICE_TRUSTED_DOWNLOAD_URLS=http://<server-ip>:8080,http://onlyoffice

USE_X_FORWARDED_HOST=False
USE_X_FORWARDED_PORT=False
SECURE_PROXY_SSL_HEADER_ENABLED=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=False
```

Notes to clarify thinsgs:
- `ONLYOFFICE_URL` is the ber-facing ONLYOFFICE URL.
- `ONLYOFFICE_INTERNAL_URL` should stay `http://onlyoffice` in Docker.
- `ONLYOFFICE_APP_BASE_URL` is the app URL ONLYOFFICE uses to fetch documents and send save callbacks.
- `ONLYOFFICE_JWT_SECRET` must match between Django and ONLYOFFICE.
- If `SECRET_KEY` contains `$`, write it as `$$` in `.env`.

## Deploy

From the server:

```bash
git clone <repo-url>
cd CE-Synopsis-Por
cp .env.template .env
# fill .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Create a superuser account for Ibrahim after deployment and send details aftewards.
