FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ARG APP_RELEASE_LABEL

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        fonts-dejavu-core \
        libcairo2 \
        libffi-dev \
        libgdk-pixbuf-2.0-0 \
        libheif1 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpq-dev \
        libwebp7 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY src /app/src
COPY README.md /app/README.md
COPY docs /app/docs
COPY .env.template /app/.env.template
COPY docker/entrypoint.sh /app/docker/entrypoint.sh

RUN chmod +x /app/docker/entrypoint.sh \
    && mkdir -p /app/src/media /app/src/staticfiles \
    && if [ -n "$APP_RELEASE_LABEL" ]; then \
        printf "%s" "$APP_RELEASE_LABEL" > /app/.release-label; \
    else \
        printf "%s" "unlabelled build" > /app/.release-label; \
    fi

WORKDIR /app/src

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
