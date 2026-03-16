# CE Synopsis Portal Roadmap

Status updated: 16 March 2026

This roadmap reflects the current state of the project more accurately than the original sprint list. A number of core workflows are already ahead of the initial plan, especially around summary authoring, synopsis compilation, and reference-library hardening.

## Current Snapshot

- Completed: protocol drafting, advisory board workflows, library/project reference import, screening, summary authoring, synopsis evidence compilation, and DOCX export.
- Current focus: make the synopsis assembly experience clearer for authors, close remaining CE-style compilation gaps, and finish the production/export pipeline.
- Main launch blockers still open: final PDF output with team-owned styling, website/API integration; and migration/cutover planning. 
- Some remaining UI/UX cleanup and performance hardening also needed based on pilot feedback, but these are less critical than the core production-readiness blockers.

## Phase 1: Foundations

- [x] Set up project structure and initial documentation.
- [x] Gather initial requirements and feedback from the CE team.
- [x] Draft and evolve core data models and database schema.
- [x] Set up PostgreSQL-backed development database.
- [x] Draft protocol-building workflow.
- [x] Draft advisory board invitation workflow.
- [x] Establish user roles and permissions.

## Phase 2: Core Workflow

- [x] Build the synopsis protocol builder.
- [x] Build the advisory board invitation and feedback workflow.
- [x] Build library import and project reference import.
- [x] Build reference screening workflow, including batch detail views and focused screening.
- [x] Build duplicate detection across library and project references.
- [x] Add baseline data-integrity hardening for imports and linking.

## Phase 3: Summary Authoring

- [x] Build the summary editor with CE-oriented metadata fields.
- [x] Support multiple full summaries per reference.
- [x] Build the summary workspace and author assignment workflow.
- [x] Add basic PDF upload/view support for references.
- [ ] Add richer PDF annotation/highlighting workflow if still required by the team.
- [ ] Build role-specific dashboards and alerts.

## Phase 4: Synopsis Compilation

- [x] Build chapter, intervention group, and intervention authoring workflow.
- [x] Support chapter background, intervention background, synthesis text, and key messages.
- [x] Support cross-reference interventions.
- [x] Support intervention-level assignment of summary tabs.
- [x] Compile numbered study paragraphs and intervention references from assigned summaries.
- [x] Support key-message citations linked to specific supporting studies.
- [x] Support multi-summary-per-paper compilation with collapsed reference lines in export.
- [x] Add author-facing compilation guidance and evidence-page UX improvements.
- [x] Generate DOCX exports of compiled synopsis content.
- [ ] Finish remaining CE-style compilation/reference rules, especially final global references output and any remaining formatting parity gaps.

## Phase 5: Pilot, Feedback, and Hardening

- [x] Run pilot-driven iteration on the summary and synopsis compilation workflows.
- [x] Improve synopsis evidence-page clarity based on author feedback.
- [x] Improve performance in key authoring views where obvious N+1 or repeated-scan issues were found.
- [x] Improve library reference integrity with unique canonical hash handling.
- [x] Improve XML import path for untrusted EndNote XML uploads.
- [ ] Continue UI/UX cleanup across workflows that remain dense or ambiguous.

## Phase 6: Production Readiness

- [ ] Implement final PDF production workflow that lets the CE team control fonts and styling for publication.
- [ ] Implement website/API integration for pushing synopsis content to the CE website.
- [ ] Finalize migration strategy for existing legacy data and in-flight projects.
- [ ] Complete launch/cutover planning with the CE team.

## Phase 7: AI Workflow/Helpers

- [ ] Explore AI-assisted tagging and summary writing helpers, with a focus on optional assistive features that don't create new data integrity issues or require manual verification of AI outputs.
- [ ] If AI helpers are viable and well-received, build them as optional features that can be toggled on/off by authors, with clear disclaimers about the need for human review and verification of any AI-generated content.

## Documentation and Enablement

- [ ] Draft synopsis authoring model documentation.
- [ ] Draft author SOP for synopsis compilation.
- [ ] Finalize end-user documentation and training materials.
- [ ] Run structured author onboarding / walkthrough sessions.

## Important but out-of-scope for now

- [ ] Integrate app with website for easier content publishing and management. 
- [ ] Migrate existing CE data from various sources (spreadsheets, EndNote libraries, etc.) into the new system, with a focus on clean-up and standardization during the migration process.
- [ ] AI-assisted screening or reference import helpers, given the higher risk of data integrity issues and the need for manual verification of AI outputs in these workflows.
- [ ] Advanced search and filtering features for references and summaries, which can be added in future iterations once the core workflows are stable and well-established.
- [ ] Improve user management and authentication, including support for single sign-on if required by the CE team. (optional)
- [ ] Optimize for users with limited internet access or older hardware, if this is a concern for the CE team. (optional)

## Notes

- The project is now beyond the original “core feature build” stage for several author workflows.
- The remaining work is less about proving the model and more about polish, compliance details, production export, integration, and rollout.
