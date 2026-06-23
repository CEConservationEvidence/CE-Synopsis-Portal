# CE Synopsis Portal

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/CEConservationEvidence/CE-Synopsis-Portal/8-synopsis-structure-and-compilation)

CE Synopsis Portal is a Django application for running Conservation Evidence synopsis projects in one place. It replaces separate fragmented files, spreadsheets, and ad hoc review email flows with a single workflow for project setup, reference handling, summary writing, synopsis assembly, review, and export.

## What The Portal Supports Today

- project hubs with phase tracking, status management, authors, and funders
- protocol and action-list workflows with revision history, draft/final states, and document download
- optional OnlyOffice collaborative editing for protocol and action-list documents
- advisory board invitations, secure response links, protocol review, action-list review, synopsis review, reminders, and custom member fields
- shared reference library import from RIS, plain text, and EndNote XML
- project reference import from RIS or plain text, plus linking from the shared library
- reference screening with shared CE subject categories stored on canonical library records
- summary workspace with author assignment, "needs help" tracking, multiple summary tabs per reference, comments, and reference PDF upload/viewing
- synopsis narrative and evidence workspaces with chapters, intervention groups, interventions, key messages, cross-references, and summary assignment
- exports for compiled synopsis DOCX, synopsis references RIS, and synopsis structure CSV

## Current Status

The core author and manager workflows are implemented. The repo now contains a working local setup, a Docker deployment stack, and dedicated Django tests around references, collaboration, advisory workflows, email, accounts, and synopsis compilation.

The main two gaps are:
- final publication-grade PDF output with CE-controlled styling/fonts
- website/API publication integration

See [docs/roadmap.md](docs/roadmap.md) for the current priority view.

## Roles

- **Manager**: creates synopses, manages users/authors/funders, controls project settings, phases, and review workflows
- **Author**: works inside assigned projects on references, summaries, documents, and synopsis content
- **External author**: limited author account without shared-library or project-creation access
- **Advisory board member**: usually interacts through secure emailed links rather than a full portal account
- **System admin**: Django superuser/staff account with broader operational access

## Tech Stack

- Python 3.12
- Django 5.2
- PostgreSQL
- Celery + Redis for queued emails, reminder scheduling, shared cache/session storage, and collaborative-session locking
- Gunicorn and WhiteNoise in the Docker deployment
- OnlyOffice Document Server integration for collaborative editing
- `python-docx` for DOCX export
- `rispy` plus custom EndNote XML/plain-text import parsing

Main application code:
- [src/synopsis](src/synopsis)
- [src/ce_portal](src/ce_portal)

## Local Setup

Prerequisites:
- Python 3.12+
- PostgreSQL
- optional Redis if you want Docker-like cache/session and Celery behavior locally
- optional OnlyOffice if you want to test collaborative editing locally

Setup:

```bash
cp .env.local.template .env.local
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then make sure the database settings in `.env.local` point at a real local PostgreSQL database. The template defaults are:
- `DB_NAME=ce_portal`
- `DB_USER=ce_user`
- `DB_PASSWORD=ce_pass`
- `DB_HOST=localhost`
- `DB_PORT=5432`

After that:

```bash
cd src
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/login/`.

Notes:
- direct Django commands automatically prefer `.env.local`, then fall back to `.env`
- use `ENV_FILE=...` to force a different env file for one command
- `post_migrate` creates the global `manager`, `author`, and `external_collaborator` groups automatically
- leaving `REDIS_CACHE_URL` blank uses local-memory cache and DB-backed sessions
- setting `REDIS_CACHE_URL=redis://localhost:6379/1` and `REDIS_CELERY_URL=redis://localhost:6379/2` gives local behavior closer to Docker
- development email defaults to the attachment-summary console backend, so messages and attachment summaries print to the terminal instead of being sent
- leaving `ONLYOFFICE_URL` blank disables collaborative editing while keeping the rest of the document workflow usable

## Running Checks

```bash
source .venv/bin/activate
cd src
python manage.py check
python manage.py test
```

`python manage.py test` requires PostgreSQL test-database access using the values from the active env file.

Example env override:

```bash
ENV_FILE=../.env.local python manage.py runserver
```

## Docker Deployment

The default Compose stack starts:
- `web`
- `db`
- `redis`
- `worker`
- `beat`
- `onlyoffice`

Quick start:

```bash
cp .env.server .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Optional HTTPS reverse proxy:
- [docker-compose.proxy.yml](docker-compose.proxy.yml)
- [docker/Caddyfile](docker/Caddyfile)

Use [docs/instructions.md](docs/instructions.md) for the full internal-server runbook, including `.env.server`, OnlyOffice wiring, Redis/Celery behavior, smoke tests, and the optional Caddy layer.

## Repository Layout

```text
.
├── docs/
│   ├── instructions.md
│   ├── reference-library-model.md
│   └── roadmap.md
├── docker/
│   ├── Caddyfile
│   └── entrypoint.sh
├── src/
│   ├── ce_portal/
│   ├── synopsis/
│   └── manage.py
├── .env.local.template
├── .env.server
├── .env.template
├── docker-compose.yml
├── docker-compose.proxy.yml
└── requirements.txt
```

## Documentation

- [docs/author-guide.md](docs/author-guide.md): author-facing onboarding guide and workflow handbook
- [docs/instructions.md](docs/instructions.md): internal Docker deployment runbook
- [docs/technical-notes.md](docs/technical-notes.md): technical architecture and component walkthrough
- [docs/roadmap.md](docs/roadmap.md): current priority and gap summary
- [docs/reference-library-model.md](docs/reference-library-model.md): how canonical library records and project references relate
- [DeepWiki project wiki](https://deepwiki.com/CEConservationEvidence/CE-Synopsis-Portal/1-overview): broader design/context notes, but it may lag behind the codebase

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

MIT License. See [LICENSE](LICENSE).

## Acknowledgements

Developed by: [Ibrahim Alhas](https://github.com/alhasacademy96).