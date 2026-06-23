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

### 7.1 Project, Audit, And Funding

Core models:

- `Project`
- `ProjectPhaseEvent`
- `ProjectChangeLog`
- `UserRole`
- `Funder`
- `FunderContact`

Important design points:

- project status is separate from phase
- phase can be inferred from related workflow state
- phase can also be manually advanced, but the manual phase cannot move behind the inferred phase
- project change history is stored explicitly in `ProjectChangeLog`

### 7.2 Documents And Revisions

Core models:

- `Protocol`
- `ProtocolRevision`
- `ActionList`
- `ActionListRevision`
- `CollaborativeSession`

Important design points:

- protocol and action list are one-to-one with a project
- each document stores a current file plus a revision history
- current stage is `draft` or `final`
- review windows can be closed independently with `feedback_closed_at`
- collaborative sessions track the initial revision, resulting revision, participant activity, and closure reason

### 7.3 Advisory Board Workflow

Core models:

- `AdvisoryBoardMember`
- `AdvisoryBoardCustomField`
- `AdvisoryBoardCustomFieldValue`
- `AdvisoryBoardCustomFieldValueHistory`
- `AdvisoryBoardInvitation`
- `ProtocolFeedback`
- `ActionListFeedback`
- `SynopsisFeedback`

Important design points:

- invitations and review feedback are tokenized with UUIDs
- protocol/action-list/synopsis review are stored separately
- feedback models snapshot the relevant document metadata and deadline context
- advisory board tables support project-specific custom fields

### 7.4 Reference Library And Screening

Core models:

- `LibraryImportBatch`
- `LibraryReference`
- `LibraryReferenceFolderHistory`
- `ReferenceSourceBatch`
- `ReferenceSourceBatchNoteHistory`
- `Reference`

Important design points:

- `LibraryReference` is the canonical shared record
- `Reference` is the project-specific working copy
- project references can point back to canonical library records
- CE subject categories live on the canonical library record for linked references
- folder/category change history is stored at the library level

### 7.5 Summary Authoring

Core models:

- `ReferenceSummary`
- `ReferenceSummaryComment`
- `ReferenceComment`
- `ReferenceActionSummary`
- `VocabularyTerm`

Important design points:

- one project reference can have multiple summary tabs
- summary tabs carry structured study metadata plus synopsis-draft text
- comments support threaded discussion and file attachments
- controlled-list/tag support exists through `VocabularyTerm`
- `ReferenceSummary` still contains AI-related fields, but the active generated-summary workflow is rule-based from structured fields rather than driven by a background AI pipeline

### 7.6 Synopsis Assembly And Export

Core models:

- `IUCNCategory`
- `SynopsisChapter`
- `SynopsisSubheading`
- `SynopsisIntervention`
- `SynopsisInterventionKeyMessage`
- `SynopsisAssignment`
- `SynopsisExportLog`

Important design points:

- synopsis content is modeled as chapters -> subheadings -> interventions
- interventions can be true evidence sections or cross-references to a primary intervention
- key messages can cite a subset of supporting summary tabs
- export events are archived in `SynopsisExportLog`

## 8. URL And Workflow Grouping

`synopsis.urls` groups routes by workflow rather than by generic CRUD resources.

Major route families:

- dashboard and auth
- project creation, settings, team, funders, and phase control
- protocol and action-list detail/revision workflows
- collaborative editing routes
- advisory board management, invitations, reminders, and review forms
- shared reference library
- project reference batches and screening
- summary board and summary detail pages
- synopsis narrative/evidence workspaces and exports

This route organization mirrors the UI and the underlying business workflow closely.

## 9. Primary Workflow Architecture

### 9.1 Project Lifecycle

The project hub is the central coordination page. It aggregates:

- current phase
- protocol/action-list state
- advisory board state
- reference and summary progress
- synopsis assembly progress

Phase behavior is hybrid:

- a best-effort phase is inferred from related activity
- users with configuration access can manually move the phase forward
- confirmations are stored in `ProjectPhaseEvent`

### 9.2 Document Workflow

Protocol and action-list pages support:

- initial upload
- subsequent revisions
- restore/delete revision operations
- draft/final state changes
- changelog entries
- optional collaborative editing

Internally, uploaded files become `ProtocolRevision` or `ActionListRevision` rows, and the current document pointer is updated to the latest applied revision.

### 9.3 Advisory Workflow

The advisory workflow is implemented as three related systems:

- invitation and participation tracking
- document review distribution
- secure feedback submission

Supported review channels:

- protocol review
- action-list review
- synopsis review

Review emails are built in the view layer and sent either synchronously or via Celery depending on settings. Review feedback links are token-based and can also optionally include a comment-only collaborative editor link for protocol/action-list review.

### 9.4 Reference Workflow

The reference pipeline is:

1. import into shared library, or import directly into a project
2. normalize and deduplicate records
3. create/reuse canonical `LibraryReference`
4. create project-level `Reference`
5. screen references as included/excluded/pending
6. included references feed the summary board

Project imports are still canonical-library aware. Even direct project imports attempt to create or reuse `LibraryReference` rows behind the scenes.

### 9.5 Summary Workflow

The summary workflow is deliberately different from the OnlyOffice document workflow. It is not live shared editing. It is a Django form workflow with conflict warnings and stale-page protection layered on top.

The summary board acts as a Kanban-like orchestration layer over `ReferenceSummary` rows.

It supports:

- author assignment
- status transitions
- `needs_help` flags
- multiple summary tabs per paper
- workload/distribution views
- bulk distribution actions
- presence tracking to reduce conflicting edits

Important board mechanics:

- included project references are ensured to have summary rows before the board is rendered
- the board polls `reference_summary_board_presence` to show which summaries currently have active authors
- a short-lived cache of summary IDs is used so board presence checks do not have to recalculate the project summary set on every request
- creating or deleting summary tabs invalidates that cache so board presence stays aligned with the current data

