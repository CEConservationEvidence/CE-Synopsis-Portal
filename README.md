# CE Synopsis Portal

_Working title. Final product name to be agreed with the Conservation Evidence team._

A Django-based workspace for planning, screening, summarising, compiling, and exporting Conservation Evidence synopses from a single system instead of scattered Word, Excel, and manual website workflows.

## Purpose & Users

This system is being built originally for the Conservation Evidence team, but the structure is intended to be reusable for other evidence-synthesis teams later.

The aim is to replace scattered Word/Excel files and manual assembly steps with one system that keeps references, summaries, synopsis structure, and exportable content in one place.

Primary users:
- **Authors**: import/search, screen, write structured study summaries, and help assemble synopsis content
- **Project managers**: draft protocols, manage projects and authors, oversee progress, and review output
- **Advisory board members**: review protocol/action-list material and provide feedback
- **Administrators**: manage users, permissions, and operational setup

## Core Expectations

These remain the main product expectations, even where implementation is still incomplete:

1. **Single source of truth**
   - References, summaries, synopsis structure, and supporting metadata should live in the database rather than separate files.

2. **End-to-end workflow**
   - The system should cover planning, protocol drafting, screening, summary writing, synopsis assembly, review, and export/publication handoff.

3. **Zero duplicate data entry**
   - Data entered once should be reused across screening, summary authoring, synopsis compilation, and export.

4. **Version control and auditability**
   - Changes should be attributable and recoverable where appropriate.

5. **Clear roles and review flow**
   - Different users should see the right tools and responsibilities for their part of the process.

6. **Usable authoring experience**
   - The interface should reduce ambiguity and make compilation behavior understandable to authors.

7. **Data quality and integrity**
   - Import validation, duplicate detection, and consistency rules should protect the underlying data.

8. **Export and interoperability**
   - The system should support clean exports and, eventually, website/API integration.

## Current Status

The project is already beyond the initial prototype stage for several core author workflows.

Implemented now:
- protocol drafting and revision workflow
- advisory board invitations and feedback workflow
- library and project reference import
- reference screening and batch review
- summary workspace, including multiple summaries per reference
- synopsis evidence authoring and compilation
- DOCX export of compiled synopsis content

Still in progress:
- final publication PDF workflow with CE-controlled styling/fonts
- API/website integration
- richer dashboards and notifications
- broader documentation, QA, and launch/cutover work

See [docs/roadmap.md](docs/roadmap.md) for the current roadmap.

## What The System Covers

Current workflow coverage:
- manage projects, users, and roles
- draft synopsis protocols
- invite and track advisory board participation
- import references into a central library
- link/import references into project batches
- screen references for inclusion/exclusion
- write structured study summaries
- assign summaries to synopsis interventions
- compile intervention evidence into exportable synopsis structure

## Minimum Viable Product Direction

The MVP is still centered on these capabilities:
- protocol drafting plus advisory workflow
- library/project reference import with validation and de-duplication
- screening workflow
- structured summary editor with CE-oriented metadata
- synopsis chapter/intervention assembly
- exportable compiled synopsis output

## Ultimate Outcome

What “good” looks like for the CE team:
- a single reliable platform used for new synopses
- far less manual copy-paste during synopsis assembly
- clearer consistency in summaries and compilation structure
- better accountability through structured workflows and stored history
- a system that other evidence-synthesis teams could adapt later

## Roles & Permissions

Current role model in broad terms:
- **Author**: create/edit summaries and synopsis content within project scope
- **Manager**: oversee projects, assign work, and access broader management actions
- **Advisory board**: review and respond to protocol/action-list/synopsis related requests
- **Admin/staff**: broader operational and system-level access

## Tech Stack

What is actually in the repo today:
- Python 3.12
- Django 5.2
- PostgreSQL
- Django REST Framework
- Celery and Redis dependencies
- WeasyPrint and `python-docx` dependencies for export/output work
- OnlyOffice configuration hooks for collaborative editing

The main application code lives in:
- [src/synopsis](src/synopsis)
- [src/ce_portal](src/ce_portal)

## Local Setup

Prerequisites:
- Python 3.12+
- PostgreSQL
- a virtual environment

Setup:

```bash
cp .env.local.template .env.local
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd src
python manage.py migrate
python manage.py runserver
```

Then open `http://127.0.0.1:8000/`.

Notes:
- direct Django commands automatically prefer `.env.local`, then fall back to `.env`
- use `ENV_FILE=...` if you want to force a different env file for a specific command
- the default database backend is PostgreSQL
- email is configured to the console backend in development

## Running Checks

```bash
source .venv/bin/activate
cd src
python manage.py check
python manage.py test
```

Example override:

```bash
ENV_FILE=../.env.local python manage.py runserver
```

## Docker Deployment

A Docker-based deployment is now included for:
- Django/Gunicorn
- PostgreSQL
- OnlyOffice Document Server

Main files:
- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)
- [docker/entrypoint.sh](docker/entrypoint.sh)

Quick start:

```bash
cp .env.template .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Detailed setup notes, including OnlyOffice URL/JWT configuration, are in [docs/docker.md](docs/docker.md).
The admin-facing handoff checklist is in [docs/admin-handoff.md](docs/admin-handoff.md).

## Repository Layout

```text
.
├── docs/
│   └── roadmap.md
├── src/
│   ├── ce_portal/
│   ├── synopsis/
│   └── manage.py
├── requirements.txt
└── README.md
```

## Documentation

Current project docs in this repo:
- [Roadmap](docs/roadmap.md)
- For a very detailed overview of the system, see the [project wiki](https://deepwiki.com/CEConservationEvidence/CE-Synopsis-Portal/1-overview). Do note that the wiki is a living document and may not always reflect the current state of the system, but it contains a lot of useful information about the design and rationale behind various features.

Additional user and technical documentation still needs to be formalized.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

MIT License. See [LICENSE](LICENSE).

## Acknowledgements

Maintainer and main developer: Ibrahim Alhas.
