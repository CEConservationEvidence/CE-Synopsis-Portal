# Internal Server Instructions - Docker Compose

For the deployment itself:

- start from [`../.env.server`](../.env.server)
- use [`../docker-compose.yml`](../docker-compose.yml)
- only look at [`../docker-compose.proxy.yml`](../docker-compose.proxy.yml) if
  the infrastructure team decides to put the app behind the optional Caddy
  reverse proxy

## How this stack works together

In the standard internal setup:

- users open the portal at `http://<server-ip>:8000`
- users open ONLYOFFICE at `http://<server-ip>:8080`
- Django talks to PostgreSQL at `db:5432`
- Django talks to Redis at `redis:6379`
- Django talks to ONLYOFFICE internally at `http://onlyoffice`
- ONLYOFFICE talks back to Django internally at `http://web:8000`

That last line is the one people usually get wrong. In the full Compose stack,
`ONLYOFFICE_APP_BASE_URL` should stay `http://web:8000`. It should not be set
to the public server IP.

## Info needed before deploy

The deployer will need:

- the server IP or internal hostname
- a Django `SECRET_KEY`
- the PostgreSQL password
- the ONLYOFFICE JWT secret
- SMTP host, port, username, and password
- the sender mailbox/address to use for portal emails

If the app will be reachable by more than one label, decide that before editing
the env file. For example:

- IP only
- hostname only
- both hostname and IP

That choice affects:

- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `ONLYOFFICE_URL`
- `ONLYOFFICE_TRUSTED_DOWNLOAD_URLS`

Try to stay consistent and use the real browser-facing host everywhere.

## Server requirements

Before deploying, check that the server has:

- Docker Engine installed
- Docker Compose plugin installed
- ports `8000` and `8080` available
- network access to the chosen SMTP server
- enough RAM and CPU for Django, PostgreSQL, Redis, Celery, and ONLYOFFICE (at least 5-6 GB RAM)

ONLYOFFICE is not a trivial sidecar. It is one of the heavier services in this
stack, so the server should be sized with that in mind. The Compose file gives
ONLYOFFICE explicit CPU and memory reservations/limits; adjust those values in
`.env` if the host is materially smaller or larger than the pilot server.

## Setting `.env`

Start by copying the server preset:

```bash
cp .env.server .env
```

Then edit `.env` with the real server values.

At minimum, make sure these are set correctly:

```env
SECRET_KEY=<django-secret>

DB_NAME=ce_portal
DB_USER=ce_user
DB_PASSWORD=<db-password>

WEB_BIND_HOST=0.0.0.0
WEB_PORT=8000
ONLYOFFICE_BIND_HOST=0.0.0.0
ONLYOFFICE_PORT=8080
ONLYOFFICE_CPU_RESERVATION=1.0
ONLYOFFICE_CPU_LIMIT=2.0
ONLYOFFICE_MEMORY_RESERVATION=2G
ONLYOFFICE_MEMORY_LIMIT=3G

REDIS_CACHE_URL=redis://redis:6379/1
REDIS_CELERY_URL=redis://redis:6379/2
COLLABORATIVE_SESSION_LOCK_TIMEOUT=30
ASYNC_EMAIL_DELIVERY=True
CELERY_LOG_LEVEL=info
CELERY_WORKER_CONCURRENCY=2

ALLOWED_HOSTS=<server-ip>
CSRF_TRUSTED_ORIGINS=http://<server-ip>:8000

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<smtp-host>
EMAIL_PORT=587
EMAIL_HOST_USER=<smtp-user>
EMAIL_HOST_PASSWORD=<smtp-password>
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=CE Synopsis Portal <pilot-mailbox@your-organisation>
SERVER_EMAIL=CE Synopsis Portal <pilot-mailbox@your-organisation>

ONLYOFFICE_URL=http://<server-ip>:8080
ONLYOFFICE_INTERNAL_URL=http://onlyoffice
ONLYOFFICE_APP_BASE_URL=http://web:8000
ONLYOFFICE_JWT_ENABLED=true
ONLYOFFICE_JWT_SECRET=<onlyoffice-jwt-secret>
ONLYOFFICE_CALLBACK_TIMEOUT=10
ONLYOFFICE_TRUSTED_DOWNLOAD_URLS=http://<server-ip>:8080,http://onlyoffice

USE_X_FORWARDED_HOST=False
USE_X_FORWARDED_PORT=False
SECURE_PROXY_SSL_HEADER_ENABLED=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=False
```

A few practical notes:

- `ONLYOFFICE_URL` is the URL the browser opens.
- `ONLYOFFICE_INTERNAL_URL` is how Django reaches ONLYOFFICE inside Docker.
- `ONLYOFFICE_APP_BASE_URL` is how ONLYOFFICE reaches Django for downloads and save callbacks.
- `ONLYOFFICE_JWT_SECRET` must match what the ONLYOFFICE container uses.
- if `SECRET_KEY` contains `$`, write it as `$$` in `.env`
- in this Compose setup, `DB_HOST` should stay `db`
- `REDIS_CACHE_URL` should stay `redis://redis:6379/1`
- `REDIS_CELERY_URL` should stay `redis://redis:6379/2`
- `COLLABORATIVE_SESSION_LOCK_TIMEOUT` controls the short Redis-backed lock around creating a live collaborative editing session.

## Deployment Steps

From the server:

```bash
git clone <repo-url>
cd CE-Synopsis-Portal
cp .env.server .env
# edit .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

This starts:

- `web`
- `db`
- `redis`
- `worker`
- `beat`
- `onlyoffice`

The Docker volumes used by this stack are:

- `postgres_data` for PostgreSQL
- `media_data` for uploaded media and saved document revisions
- `onlyoffice_data` for ONLYOFFICE data

The first startup can take a little while because:

- Django runs migrations automatically
- Django collects static files automatically
- ONLYOFFICE can take a while to finish starting up

Also worth knowing:

- `worker` and `beat` run as a non-root app user
- `web` still follows the existing startup path, including migrations and static collection

## What Redis and Celery Are Doing Here

In this deployment:

- Redis backs the shared Django cache
- Redis backs `cached_db` sessions
- Celery worker runs background jobs
- Celery beat schedules the advisory reminder task hourly
- invite/review/access emails are queued through Celery instead of blocking the web request on SMTP

So for the internal server deployment, Redis should be treated as required.

## ONLYOFFICE Smoke Test (VERY IMPORTANT!)

After deployment:

1. open `http://<server-ip>:8000`
2. log in as a superuser
3. open a project with a protocol or action list
4. choose `Open collaborative editor` (loads new window)
5. confirm the ONLYOFFICE editor loads (so the doucment loads and the toolbar appears)
6. make a change, return to the detail page, and confirm the revision saved

If the editor page opens but the document itself does not load, check these
first:

- `ONLYOFFICE_URL`
- `ONLYOFFICE_INTERNAL_URL`
- `ONLYOFFICE_APP_BASE_URL`
- matching `ONLYOFFICE_JWT_SECRET`
- `ONLYOFFICE_TRUSTED_DOWNLOAD_URLS`

The most common failure pattern is:

- the browser can open ONLYOFFICE
- but ONLYOFFICE cannot fetch the document or send the save callback back to Django
- because `ONLYOFFICE_APP_BASE_URL` points to the wrong host

Again, in the full Compose stack, that value should stay `http://web:8000`.

## Email / Celery Smoke Test (NOT CURRENTLY IMPLEMENTED -- skip for now)

Because review and invitation emails are queued, a healthy deployment depends
on all of these working together:

- `redis`
- `worker`
- `beat`
- valid SMTP settings

Minimum email check:

1. send a test advisory invitation or review email from the portal
2. confirm the UI says `queued` or `sent`
3. check `docker compose logs worker`
4. confirm the recipient actually receives the email

### GitHub Secrets Needed

Set these repository secrets before turning the deploy job on:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_PATH`
- `DEPLOY_SSH_KEY`

Optional:

- `DEPLOY_PORT`
- `DEPLOY_KNOWN_HOSTS`

Optional repository variable:

- `ENABLE_DEPLOY`
  - set this to `true` when you actually want GitHub Actions to redeploy the server
  - if this is left unset, the deploy job stays off and only CI runs
- `DEPLOY_BRANCH`
  - defaults to `main` if you do not set it

If you use `DEPLOY_KNOWN_HOSTS`, put the server's known-host entry there and
the workflow will use it directly. If you leave it blank, the workflow will use
`ssh-keyscan` at runtime.

## Useful Commands

Check service state:

```bash
docker compose ps
```

Tail logs:

```bash
docker compose logs -f web
docker compose logs -f worker
docker compose logs -f beat
docker compose logs -f onlyoffice
```

Run checks manually:

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py send_due_reminders
```

## Updating Later (CI/CD)

For an update:

```bash
git pull
docker compose up --build -d
docker compose exec web python manage.py check
```

Finally, please create a superuser and share the credentials with the team so we can log in and check the admin if needed.