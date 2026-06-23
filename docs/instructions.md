# Internal Server Deployment Runbook

This runbook describes the Docker Compose deployment that is committed in this repository.

Use:
- [`../.env.server`](../.env.server) as the starting env file
- [`../docker-compose.yml`](../docker-compose.yml) for the base stack
- [`../docker-compose.proxy.yml`](../docker-compose.proxy.yml) and [`../docker/Caddyfile`](../docker/Caddyfile) only if you want the optional HTTPS reverse proxy

## Default Topology

In the base stack:

- users open the portal at `http://<server>:8000`
- users open OnlyOffice at `http://<server>:8080`
- Django talks to PostgreSQL at `db:5432`
- Django talks to Redis at `redis:6379`
- Django talks to OnlyOffice internally at `http://onlyoffice`
- OnlyOffice talks back to Django internally at `http://web:8000`

The last item is the one that matters most for collaborative editing. In the full Compose stack, `ONLYOFFICE_APP_BASE_URL` should stay `http://web:8000`. Do not point it at the public server IP.

## Information Before Deploying

- server IP or hostname
- Django `SECRET_KEY`
- PostgreSQL password
- OnlyOffice JWT secret
- SMTP host, port, username, and password
- sender mailbox/address for portal email

If you are using the optional Caddy layer, also decide:
- portal hostname for `APP_DOMAIN`
- OnlyOffice hostname for `ONLYOFFICE_DOMAIN`
- ACME email for `ACME_EMAIL`

Be consistent about the browser-facing hostname(s). That affects:
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `ONLYOFFICE_URL`
- `ONLYOFFICE_TRUSTED_DOWNLOAD_URLS`

## Server Requirements

- Docker Engine installed
- Docker Compose plugin installed
- ports `8000` and `8080` available for the base stack
- ports `80` and `443` available if using the optional Caddy layer
- outbound network access to the SMTP server
- enough RAM/CPU for Django, PostgreSQL, Redis, Celery, and OnlyOffice

Min 5-6 GB RAM as a practical minimum. OnlyOffice is the heaviest service in this stack. The Compose file already includes CPU and memory controls for it through env vars.

## Configure `.env`

Start by copying the committed server preset:

```bash
cp .env.server .env
```

Then edit `.env`.

At minimum, review and replace:

```env
SECRET_KEY=replace-with-django-secret-key

DB_PASSWORD=replace-with-db-password

ALLOWED_HOSTS=server-ip-or-hostname
CSRF_TRUSTED_ORIGINS=http://server-ip-or-hostname:8000

EMAIL_HOST=replace-with-smtp-host
EMAIL_PORT=587
EMAIL_HOST_USER=replace-with-smtp-user
EMAIL_HOST_PASSWORD=replace-with-smtp-password
DEFAULT_FROM_EMAIL=CE Synopsis Portal <pilot-mailbox@your-organisation>
SERVER_EMAIL=CE Synopsis Portal <pilot-mailbox@your-organisation>

ONLYOFFICE_URL=http://server-ip-or-hostname:8080
ONLYOFFICE_INTERNAL_URL=http://onlyoffice
ONLYOFFICE_APP_BASE_URL=http://web:8000
ONLYOFFICE_JWT_SECRET=replace-with-onlyoffice-jwt-secret
ONLYOFFICE_TRUSTED_DOWNLOAD_URLS=http://server-ip-or-hostname:8080,http://onlyoffice
```

Important notes:

- `DB_HOST` should stay `db` in this deployment
- `REDIS_CACHE_URL` should stay `redis://redis:6379/1`
- `REDIS_CELERY_URL` should stay `redis://redis:6379/2`
- `ONLYOFFICE_URL` is the browser-facing Document Server URL
- `ONLYOFFICE_INTERNAL_URL` is how Django reaches Document Server inside Docker
- `ONLYOFFICE_APP_BASE_URL` is how Document Server reaches Django for downloads and save callbacks
- `ONLYOFFICE_JWT_SECRET` must match the OnlyOffice container setting
- if `SECRET_KEY` contains `$`, escape it as `$$` in `.env`
- `ASYNC_EMAIL_DELIVERY=True` is the expected deployment mode so web requests do not block on SMTP

If you are exposing the portal directly over HTTP on an internal server, keep:
- `USE_X_FORWARDED_HOST=False`
- `USE_X_FORWARDED_PORT=False`
- `SECURE_PROXY_SSL_HEADER_ENABLED=False`
- `SESSION_COOKIE_SECURE=False`
- `CSRF_COOKIE_SECURE=False`
- `SECURE_SSL_REDIRECT=False`

If you put the app behind a real HTTPS reverse proxy, review those values before go-live.

## Deploy The Stack

Base stack:

```bash
git clone <repo-url>
cd CE-Synopsis-Portal
cp .env.server .env
# edit .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Optional Caddy HTTPS layer:

```bash
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up --build -d
```

What starts:
- `web`
- `db`
- `redis`
- `worker`
- `beat`
- `onlyoffice`
- `caddy` if the proxy override is included

The first startup can take a while because:
- Django runs migrations automatically in the `web` container
- Django collects static files automatically in the `web` container
- OnlyOffice can take time to become ready

The base stack uses these Docker volumes:
- `postgres_data` for PostgreSQL
- `media_data` for uploaded files and saved revisions
- `onlyoffice_data` for Document Server state

## What Redis And Celery Do Here

In this deployment:

- Redis backs the shared Django cache
- Redis backs `cached_db` sessions
- Redis backs Celery broker/result storage
- Celery worker sends queued portal email
- Celery beat schedules the hourly advisory reminder task
- Redis also backs the short lock used when creating collaborative sessions

For this deployment model, Redis should be treated as required.

## Smoke Tests

### Portal

1. Open `http://<server>:8000`.
2. Sign in as the superuser you created.
3. Open an existing project or create a small test project.
4. Confirm the dashboard, project hub, and shared reference library load.

### Collaborative Editing

1. Upload a protocol or action-list document.
2. Choose `Open collaborative editor`.
3. Confirm the OnlyOffice editor and toolbar load.
4. Make a small edit.
5. Close the collaborative round from the portal.
6. Confirm a new revision is saved on the relevant detail page.

If the editor window opens but the document itself does not load, check:
- `ONLYOFFICE_URL`
- `ONLYOFFICE_INTERNAL_URL`
- `ONLYOFFICE_APP_BASE_URL`
- matching `ONLYOFFICE_JWT_SECRET`
- `ONLYOFFICE_TRUSTED_DOWNLOAD_URLS`

The common failure pattern is that the browser can open OnlyOffice, but OnlyOffice cannot fetch the document or post the save callback back to Django because `ONLYOFFICE_APP_BASE_URL` points at the wrong host.

### Email / Worker

1. Send a test advisory invitation or review email from the portal.
2. Confirm the UI reports the email as queued or sent.
3. Check worker logs:
   ```bash
   docker compose logs worker
   ```
4. Confirm the recipient receives the message.

If email does not send, check:
- `EMAIL_*` settings
- `ASYNC_EMAIL_DELIVERY`
- `REDIS_CELERY_URL`
- that `worker` is running and healthy

## Operational Commands

Useful log commands:

```bash
docker compose logs web
docker compose logs worker
docker compose logs beat
docker compose logs onlyoffice
```

Run Django checks manually:

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py send_due_reminders
```

Restart after env/config changes:

```bash
docker compose up -d --build
```

## Backups

Back up at least:
- PostgreSQL data from `postgres_data`
- uploaded/revision files from `media_data`

`onlyoffice_data` is also worth preserving if you want the Document Server cache/state retained across host rebuilds.

