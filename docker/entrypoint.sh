#!/bin/sh
set -e

python - <<'PY'
import os
import time

import psycopg

host = os.getenv("DB_HOST", "db")
port = int(os.getenv("DB_PORT", "5432"))
dbname = os.getenv("DB_NAME", "")
user = os.getenv("DB_USER", "")
password = os.getenv("DB_PASSWORD", "")
timeout = int(os.getenv("DB_WAIT_TIMEOUT", "60"))
deadline = time.time() + timeout

while True:
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=5,
        )
        conn.close()
        break
    except Exception as exc:
        if time.time() >= deadline:
            raise SystemExit(
                f"Database did not become ready within {timeout}s: {exc}"
            )
        time.sleep(2)
PY

if [ "${RUN_APP_INIT:-True}" = "True" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
fi

if [ "$#" -eq 0 ]; then
    set -- \
        gunicorn ce_portal.wsgi:application \
        --bind 0.0.0.0:8000 \
        --worker-class gthread \
        --workers "${GUNICORN_WORKERS:-3}" \
        --threads "${GUNICORN_THREADS:-8}" \
        --timeout "${GUNICORN_TIMEOUT:-300}" \
        --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
        --keep-alive "${GUNICORN_KEEP_ALIVE:-5}" \
        --access-logfile - \
        --error-logfile -
fi

exec "$@"
