FROM python:3.12-slim AS release-metadata

WORKDIR /build

COPY . /build/context

RUN python - <<'PY'
from pathlib import Path


def resolve_ref(git_dir: Path, ref: str) -> str:
    ref_path = git_dir / ref
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8").strip()

    packed_refs = git_dir / "packed-refs"
    if packed_refs.exists():
        for line in packed_refs.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            sha, _, name = line.partition(" ")
            if name == ref:
                return sha.strip()
    return ""

git_dir = Path("/build/context/.git")
if not git_dir.exists():
    Path("/release-label").write_text("unlabelled build", encoding="utf-8")
    raise SystemExit(0)

head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
branch = ""
commit = ""

if head.startswith("ref: "):
    ref = head[5:].strip()
    branch = ref.rsplit("/", 1)[-1]
    commit = resolve_ref(git_dir, ref)
else:
    commit = head

short_sha = commit[:7] if commit else ""
label = f"{branch}@{short_sha}" if branch and short_sha else short_sha or "unlabelled build"
Path("/release-label").write_text(label, encoding="utf-8")
PY

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

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
COPY --from=release-metadata /release-label /app/.release-label

RUN chmod +x /app/docker/entrypoint.sh \
    && mkdir -p /app/src/media /app/src/staticfiles

WORKDIR /app/src

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "ce_portal.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
