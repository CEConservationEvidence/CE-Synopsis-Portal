# Docker Deployment

This repo now includes a Docker-based runtime for:
- the Django app
- PostgreSQL
- OnlyOffice Document Server

The main files are:
- [`Dockerfile`](../Dockerfile)
- [`docker-compose.yml`](../docker-compose.yml)
- [`docker-compose.proxy.yml`](../docker-compose.proxy.yml)
- [`docker/entrypoint.sh`](../docker/entrypoint.sh)
- [`docker/Caddyfile`](../docker/Caddyfile)

## What The Containers Do

- `web`: builds the Django app image, waits for PostgreSQL, runs migrations, collects static files, then starts Gunicorn on port `8000`
- `db`: PostgreSQL database
- `onlyoffice`: OnlyOffice Document Server on port `8080`

## 1. Prepare The Server

Install:
- Docker Engine
- Docker Compose plugin

Clone the repo:

```bash
git clone <your-repo-url>
cd CE-Synopsis-Portal
```

## 2. Create The Environment File

Copy the template:

```bash
cp .env.template .env
```

This Docker path continues to use `.env`. Direct non-Docker Django commands can
use `.env.local` independently.

Fill in at least:
- `SECRET_KEY`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DEFAULT_FROM_EMAIL`
- `ONLYOFFICE_JWT_SECRET`

Important:
- if `SECRET_KEY` contains `$`, escape it as `$$` in the env file for Docker Compose
- or generate a key without `$` characters

## 3. Set The Public URLs Correctly

For this app, OnlyOffice must be reachable from:
- the browser
- the Django container

That means you should use a hostname or server IP that both can resolve.

Example for a server at `203.0.113.10`:

```env
ALLOWED_HOSTS=203.0.113.10,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://203.0.113.10:8000
ONLYOFFICE_URL=http://203.0.113.10:8080
ONLYOFFICE_INTERNAL_URL=http://onlyoffice
ONLYOFFICE_APP_BASE_URL=http://203.0.113.10:8000
ONLYOFFICE_TRUSTED_DOWNLOAD_URLS=http://203.0.113.10:8080,http://onlyoffice
```

If you later put the stack behind HTTPS and a reverse proxy, update these to the final HTTPS URLs.

For local Docker Desktop testing, the browser and the OnlyOffice container do
not resolve `localhost` the same way. Keep `ONLYOFFICE_URL=http://localhost:8080`
for the browser, and set:

```env
ONLYOFFICE_INTERNAL_URL=http://onlyoffice
ONLYOFFICE_APP_BASE_URL=http://host.docker.internal:8000
```

That makes:
- Django -> OnlyOffice use the Docker service hostname
- OnlyOffice -> Django use the Docker host bridge

## 3a. Configure ONLYOFFICE JWT The Docker Way

The official ONLYOFFICE Docs guidance for Docker is:
- use environment variables, not manual edits to `local.json`
- set `JWT_ENABLED=true`
- set `JWT_SECRET` to your chosen shared secret

This repo already follows that approach:
- `.env` uses `ONLYOFFICE_JWT_SECRET`
- `docker-compose.yml` passes that to the `onlyoffice` container as `JWT_SECRET`
- Django reads the same `.env` value as `ONLYOFFICE_JWT_SECRET`

Important:
- the Django app and the `onlyoffice` container must use the same secret
- if you disable JWT for troubleshooting, set `ONLYOFFICE_JWT_ENABLED=False` in `.env`
- for a real hosted environment, leave JWT enabled

Example:

```env
ONLYOFFICE_JWT_ENABLED=true
ONLYOFFICE_JWT_SECRET=replace-this-with-a-long-random-secret
```

## 3b. If You Put Django Behind HTTPS Later

When you add Nginx or Caddy in front of Django, also set these in `.env`:

```env
USE_X_FORWARDED_HOST=True
USE_X_FORWARDED_PORT=True
SECURE_PROXY_SSL_HEADER_ENABLED=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
```

Do not turn those on while serving Django directly over plain HTTP, or login
cookies and redirects will behave incorrectly.

## 4. Start The Stack

```bash
docker compose up --build -d
```

This will:
- build the Django image
- start PostgreSQL
- run migrations automatically
- collect static files automatically
- start Gunicorn
- start OnlyOffice

## 4a. Recommended Online Pilot: Use The Caddy HTTPS Layer

For a team-accessible online pilot, prefer:
- one hostname for Django, for example `synopsis.example.org`
- one hostname for OnlyOffice, for example `docs.example.org`
- HTTPS terminated by Caddy

In `.env`, set:

```env
APP_DOMAIN=synopsis.example.org
ONLYOFFICE_DOMAIN=docs.example.org
ACME_EMAIL=admin@example.org
WEB_BIND_HOST=127.0.0.1
ONLYOFFICE_BIND_HOST=127.0.0.1
ALLOWED_HOSTS=synopsis.example.org
CSRF_TRUSTED_ORIGINS=https://synopsis.example.org
ONLYOFFICE_URL=https://docs.example.org
ONLYOFFICE_TRUSTED_DOWNLOAD_URLS=https://docs.example.org,http://onlyoffice
USE_X_FORWARDED_HOST=True
USE_X_FORWARDED_PORT=True
SECURE_PROXY_SSL_HEADER_ENABLED=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
```

Then start the full stack with:

```bash
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up --build -d
```

Caddy will proxy:
- `APP_DOMAIN` -> Django/Gunicorn
- `ONLYOFFICE_DOMAIN` -> OnlyOffice Document Server

## 5. Create An Admin User

```bash
docker compose exec web python manage.py createsuperuser
```

## 6. Open The Services

- App: `http://<server-host>:8000`
- OnlyOffice: `http://<server-host>:8080`

If using the optional Caddy layer instead:
- App: `https://<APP_DOMAIN>`
- OnlyOffice: `https://<ONLYOFFICE_DOMAIN>`

If you switch email delivery away from the console backend for the hosted pilot,
set the SMTP-related environment variables in `.env` as well:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-user
EMAIL_HOST_PASSWORD=your-password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=CE Synopsis Portal <noreply@example.com>
SERVER_EMAIL=CE Synopsis Portal <noreply@example.com>
```

## 7. Updating The App Later

```bash
git pull
docker compose up --build -d
```

## Notes

- Uploaded files are stored in the `media_data` Docker volume.
- PostgreSQL data is stored in the `postgres_data` Docker volume.
- OnlyOffice data is stored in the `onlyoffice_data` Docker volume.
- The app serves uploaded media itself in this container setup (`SERVE_MEDIA=True` in compose).
- Static files are collected and served by WhiteNoise inside the Django container.

## Operational Recommendation

For the online server, the cleanest next step after this is:
- keep Docker Compose for the app stack
- place Nginx or Caddy in front of it
- terminate HTTPS there
- point a real hostname at the server

That is not required for the basic stack to run, but it is the right direction for a more durable deployment.

See also [`admin-handoff.md`](admin-handoff.md) for the ownership split and the checklist you can send directly to admins.
