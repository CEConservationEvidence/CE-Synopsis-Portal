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

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
