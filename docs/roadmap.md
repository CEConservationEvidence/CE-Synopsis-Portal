# CE Synopsis Portal Roadmap

_Status updated: 20 June 2026 by Ibrahim Alhas._

This roadmap reflects the current repository state rather than the older sprint framing.

## Current Snapshot

- The core synopsis workflow is implemented end to end: project setup, protocol/action-list handling, advisory review, shared reference library, project imports, screening, summary writing, synopsis assembly, and export.
- Collaborative editing for protocols and action lists is implemented through OnlyOffice.
- Advisory review now covers invitations, protocol review, action-list review, and synopsis review.
- The main remaining blockers are publication output, external publication integration, and rollout/cutover work rather than basic workflow viability.

## Implemented

### Project and User Workflow

- [x] Project hubs with phase tracking, status management, author assignment, and funders
- [x] Manager dashboard and user-management screens
- [x] External-author access model for limited project-only access

### Documents and Review

- [x] Protocol upload, revision history, draft/final workflow, and restore/delete controls
- [x] Action-list upload, revision history, draft/final workflow, and restore/delete controls
- [x] OnlyOffice collaborative editing for protocol and action-list documents
- [x] Advisory invitation emails with secure response links
- [x] Protocol review workflow
- [x] Action-list review workflow
- [x] Synopsis review workflow
- [x] Queued outbound email and scheduled reminder task via Celery/Redis

### References and Screening

- [x] Shared canonical reference library
- [x] Library import from RIS, plain text, and EndNote XML
- [x] Project import from RIS and plain text
- [x] Link-from-library workflow into projects
- [x] Duplicate detection across library and project imports
- [x] Shared CE subject-category model on canonical library records
- [x] Project-level screening workflow with included/excluded/pending states

### Summary Authoring

- [x] Summary board with assignment, status columns, and workload/distribution view
- [x] Multiple summary tabs per reference
- [x] Summary comments and presence tracking
- [x] Reference PDF upload/view support
- [x] Structured summary fields, synopsis-draft fields, and export citation overrides

### Synopsis Assembly And Export

- [x] Narrative and evidence workspaces
- [x] Chapters, intervention groups, interventions, and key messages
- [x] Cross-reference interventions
- [x] Summary-to-intervention assignment
- [x] DOCX export of compiled synopsis content
- [x] RIS export of synopsis references
- [x] CSV export of synopsis structure

### Deployment

- [x] Local `.env.local` workflow
- [x] Docker Compose deployment for Django, PostgreSQL, Redis, Celery, and OnlyOffice
- [x] Entrypoint script with database initialization and migration handling
- [x] Caddy reverse-proxy layer

## Current Priorities

- [ ] Finish the publication-grade PDF workflow with CE-controlled styling/fonts
- [ ] Close remaining CE-specific formatting/parity gaps in compiled output
- [ ] Improve clarity and reduce density in the heaviest authoring screens
- [ ] Expand end-user guidance and training material

## Major Open Gaps

- [ ] Website/API integration for publishing synopsis output outside the portal
- [ ] Migration for legacy CE data and in-flight work (e.g. Endnote XML imports, RIS imports)
- [ ] More formal operational guidance around backups, restore, and production maintenance
- [ ] Broader notification/alerting beyond the current email/reminder flows

## Lower-Priority or Exploratory Work

- [ ] Richer PDF annotation/highlighting workflow
- [ ] Advanced search/filtering improvements once the core workflows settle
- [ ] Broader authentication changes if required later
- [ ] AI-assisted helpers only if they remain optional, reviewable, and low-risk for data integrity

## Documentation and Enablement

- [x] Deployment runbook in `docs/instructions.md`
- [x] Author-facing guidebook for using the portal, including screenshots and workflow explanations in `docs/author-guide.md`
- [x] Internal developer documentation for the codebase, including architecture and workflow notes in `docs/technical-notes.md`
