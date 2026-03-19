# Docker Notes

This is a short technical reference for the Docker runtime in this repo.

If you are deploying the pilot on a server, use [`admin-handoff.md`](admin-handoff.md) first. This file is just background on how the Docker setup is wired.

## Files

- [`Dockerfile`](../Dockerfile)
- [`docker-compose.yml`](../docker-compose.yml)
- [`docker-compose.proxy.yml`](../docker-compose.proxy.yml)
- [`docker/entrypoint.sh`](../docker/entrypoint.sh)
- [`docker/Caddyfile`](../docker/Caddyfile)

## Services

- `web`: Django app behind Gunicorn on port `8000`
- `db`: PostgreSQL
- `onlyoffice`: ONLYOFFICE Document Server on port `8080`

Optional:
- `caddy`: reverse proxy and HTTPS when using `docker-compose.proxy.yml`

## Basic Run

```bash
cp .env.template .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

## Key Environment Variables

Most of the Docker-specific setup comes down to these:

- `SECRET_KEY`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `ONLYOFFICE_URL`
- `ONLYOFFICE_INTERNAL_URL`
- `ONLYOFFICE_APP_BASE_URL`
- `ONLYOFFICE_JWT_SECRET`
- `ONLYOFFICE_TRUSTED_DOWNLOAD_URLS`

Email for pilot testing:
- `EMAIL_BACKEND`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `DEFAULT_FROM_EMAIL`

## ONLYOFFICE URL Rules

The ONLYOFFICE setup works when these three URLs are set correctly:

- `ONLYOFFICE_URL`: what the browser opens
- `ONLYOFFICE_INTERNAL_URL`: how Django reaches ONLYOFFICE inside Docker
- `ONLYOFFICE_APP_BASE_URL`: how ONLYOFFICE reaches Django for downloads and save callbacks

For the current Docker setup:
- leave `ONLYOFFICE_INTERNAL_URL=http://onlyoffice`
- keep the same `ONLYOFFICE_JWT_SECRET` in Django and ONLYOFFICE

## Local Docker Desktop Note

For local Docker Desktop testing, the browser and the containers do not resolve `localhost` the same way.

Typical local values are:

```env
ONLYOFFICE_URL=http://localhost:8080
ONLYOFFICE_INTERNAL_URL=http://onlyoffice
ONLYOFFICE_APP_BASE_URL=http://host.docker.internal:8000
ONLYOFFICE_TRUSTED_DOWNLOAD_URLS=http://localhost:8080,http://onlyoffice
```

## Data Volumes

- PostgreSQL data: `postgres_data`
- uploaded media and saved revisions: `media_data`
- ONLYOFFICE data: `onlyoffice_data`

## Updating

```bash
git pull
docker compose up --build -d
```

## Notes

- the container entrypoint runs migrations and collects static files automatically
- uploaded media is served by Django in this Docker setup
- if a Docker Compose `SECRET_KEY` contains `$`, write it as `$$`
