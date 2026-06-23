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

## 3. Repository Structure

Main areas of the repository:

- `src/manage.py`
  - standard Django management entry point
- `src/ce_portal/`
  - project-level configuration: settings, root URLs, Celery bootstrap, ASGI/WSGI
- `src/synopsis/`
  - the main application: models, views, forms, tasks, utilities, admin, services, templates, tests
- `src/templates/`
  - Django templates, mostly grouped under `synopsis/`
- `docker-compose.yml`
  - application stack with Django, PostgreSQL, Redis, Celery, and OnlyOffice
- `docker-compose.proxy.yml` and `docker/Caddyfile`
  - optional HTTPS reverse-proxy layer

Useful code landmarks:

- `src/synopsis/models.py`
  - core domain model for projects, documents, references, summaries, synopsis structure, and review workflows
- `src/synopsis/forms.py`
  - workflow-specific validation and field shaping for the large form-driven pages
- `src/synopsis/views.py`
  - the main orchestration layer; most business rules and state transitions still live here
- `src/templates/synopsis/`
  - server-rendered UI for all major workflows
- `src/synopsis/tasks.py`
  - queued email delivery and scheduled reminder execution
- `src/synopsis/tests/`
  - integration-heavy Django test coverage grouped by workflow

Architecturally, the codebase is centered on:

- **models** for domain state
- **forms** for validation and workflow-specific input handling
- **views** for orchestration
- **templates** for UI
- **tasks** for asynchronous email and scheduled reminders

One important characteristic is that `src/synopsis/views.py` is a large orchestration module. The architecture is workflow-centric rather than heavily layered, so it is normal for one route handler to validate forms, update models, write audit logs, and choose the next UI state in the same function.

## 4. Application Startup And Configuration

### 4.1 Environment Resolution

`ce_portal.settings` resolves environment in this order:

1. `ENV_FILE` if explicitly set
2. `.env.local`
3. `.env`
4. normal environment lookup through `python-decouple`

This lets local development and Docker deployment use different env files without changing code.

### 4.2 Core Settings

Important settings behavior:

- database backend is always PostgreSQL
- Redis-backed cache/session behavior is enabled only when `REDIS_CACHE_URL` is present and tests are not running
- `CELERY_BROKER_URL` is taken from `REDIS_CELERY_URL`
- `ASYNC_EMAIL_DELIVERY` defaults to enabled when a Celery broker is configured and `DEBUG` is false, but can be overridden explicitly
- Celery beat schedules the `send_due_reminders_task` hourly when `REDIS_CELERY_URL` is configured
- development email defaults to `AttachmentSummaryConsoleEmailBackend`, which prints message content without dumping attachment payloads
- OnlyOffice is configured through the `ONLYOFFICE` dict in settings
- the OnlyOffice settings bundle includes `base_url`, `internal_url`, `app_base_url`, `jwt_secret`, `callback_timeout`, and `trusted_download_urls`
- WhiteNoise is enabled only if installed

### 4.3 Django Boot Hooks

`SynopsisConfig.ready()` imports `synopsis.signals`.

`post_migrate` signal behavior:

- ensures the global Django auth groups `manager`, `author`, and `external_collaborator` exist

### 4.4 Root Routing

`ce_portal.urls` is intentionally small:

- `/admin/` -> Django admin
- `/` -> `synopsis.urls`

Media serving behavior:

- in `DEBUG`, Django serves media directly
- outside `DEBUG`, media can still be served by Django if `SERVE_MEDIA=True`
- that `SERVE_MEDIA` path is intended for internal/pilot deployments and does not provide per-file auth checks

## 5. Rendering Model And Request Handling

The UI is server-rendered with Django templates and Bootstrap.

The common request pattern is:

1. a route in `synopsis.urls` resolves to a workflow view
2. the view checks authentication and project-scoped permissions
3. the view loads or materializes the related rows it needs
4. if the page supports several operations, the POST branch switches behavior using a hidden `action` field
5. successful writes usually add a Django message, record change history, and redirect
6. failed validation re-renders the same template with inline errors

Technical characteristics:

- form submissions are the main state transition mechanism
- large workflow pages often host multiple forms and multiple POST actions on the same URL
- there is some targeted JavaScript for UI behaviors, filters, and presence updates
- there is no first-party REST API exposed by the root URL configuration
- auth flows reuse Django auth views with custom templates/forms

Custom auth wrappers in `synopsis.views`:

- `PortalLoginView`
- `PortalLogoutView`
- `PortalPasswordResetView`
- `PortalPasswordResetConfirmView`

## 6. Roles And Permission Model

Permissions are enforced through a mix of:

- Django auth flags and groups
- project-scoped `UserRole` rows
- helper predicates in `synopsis.views`

Key rules:

- **Manager** is effectively `is_staff` or in the `manager` group
- **Author** can work inside assigned projects
- **External author** is intentionally restricted from creating projects or managing the shared library; the bootstrapped Django auth group name for this role is `external_collaborator`
- **Advisory board member** usually operates through secure emailed tokens rather than a normal portal session

Important permission helpers:

- `_user_is_manager()`
- `_user_can_manage_library()`
- `_user_can_view_project()`
- `_user_can_manage_project_configuration()`
- `_user_can_edit_project()`

Navigation also reflects permissions through `synopsis.context_processors.navigation_roles`.

## 7. Data Model By Subsystem
