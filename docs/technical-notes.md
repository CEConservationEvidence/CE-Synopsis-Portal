# Technical Notes

_Status updated: 21 June 2026 by Ibrahim Alhas._

This document explains how CE Synopsis Portal works at a technical level: the runtime stack, code organization, data model, workflow orchestration, background processing, and the OnlyOffice integration.

If you are tracing behaviour in the code, the usual path is:

1. start in `src/synopsis/urls.py`
2. follow the route into `src/synopsis/views.py`
3. inspect the matching form, model, and template

## 1. System Overview

CE Synopsis Portal is a server-rendered Django application for managing Conservation Evidence synopsis projects end to end. The application is built around one main Django app, synopsis, which contains almost all workflow logic.

The core mental model is:

- Django renders pages and handles most state transitions through forms and POST actions
- PostgreSQL stores the durable workflow state
- Redis, when enabled, provides shared cache/session behavior and Celery coordination
- OnlyOffice is an external editor used only for collaborative protocol and action-list editing

At a high level, the system supports:

- project and user management
- protocol and action-list document handling
- collaborative document editing through OnlyOffice
- advisory board invitation and review workflows
- shared reference library and project-level screening
- structured reference-summary authoring
- synopsis assembly in narrative and evidence workspaces
- export to DOCX, RIS, and CSV

The application is not currently structured as a public API platform or SPA. It is primarily a route-driven, template-rendered Django system using classic POST/redirect/GET flows.

## 2. Runtime Topology

The production-style Docker deployment uses a small set of long-lived services. Not every service talks directly to every other service.

```text
Normal pages:
Browser <-> Django / Gunicorn (`web`)
Django / Gunicorn <-> PostgreSQL (`db`)
Django / Gunicorn <-> Redis (`redis`)
Celery worker (`worker`) <-> Redis
Celery beat (`beat`) -> Redis / Celery worker

Collaborative document pages add:
Browser <-> OnlyOffice Document Server (`onlyoffice`)
OnlyOffice Document Server <-> Django / Gunicorn (`web`)
```

Component responsibilities:

- **Django/Gunicorn**: serves HTML, handles forms, permissions, workflow actions, exports, and OnlyOffice callbacks.
- **PostgreSQL**: primary relational data store for all domain models.
- **Redis**: shared cache, `cached_db` session backend when enabled, Celery broker/result backend, summary/editor presence caching, and collaborative-session lock coordination.
- **Celery worker**: runs queued tasks from the same Django codebase, currently mostly async email delivery.
- **Celery beat**: triggers the reminder task hourly.
- **OnlyOffice Document Server**: serves the live editor UI to the browser, downloads the current document from Django, and posts save/close callbacks back to Django.
