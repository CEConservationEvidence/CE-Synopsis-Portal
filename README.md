# "CE Synthesis Portal" (working title, name to be agreed with the CE team)

A unified, open-source workspace to **plan, search, screen, summarise, review, assemble and publish** Conservation Evidence synopses — with one source of truth, clear roles, and minimal copy–paste. This repository will be self-contained, meaning it will house both the documentation and the codebase.

---

## Purpose

Create a single, central tool that replaces scattered Word/Excel files and manual CMS steps. This tool will (eventaully) make it **faster, clearer, and less error-prone** for the CE team to produce synopses, while remaining flexible enough to reuse for other “living evidence” topics.

---

## Who it serves

- **Authors** – import/search, screen, write 200-word summaries, tag studies.
- **[CE] Project Manager** – officially invite advisory board members, oversee progress, review/approve, manage timelines.
- **Data Manager** – manage imports, vocabularies, consistency checks.
- **Advisory Board** – view protocols, comment, approve scope/actions; provide their input directly.

---

## Core expectations (high-level, v1, subject to change)

1. **Single source of truth**
   - All references, summaries, tags, backgrounds, key messages, actions and search logs live in the database.
   - No hard-coded domain lists (e.g., species); use editable controlled vocabularies.

2. **End-to-end workflow**
   - Plan & protocol: draft, version, share with the board.
   - Import & screen: ingest RIS, detect duplicates, include/exclude with reasons.
   - Summarise & tag: rich editor with 200-word guardrails and structured fields.
   - Review & approve: role-based workflows, comments, change requests.
   - Assemble & publish: compile chapters/actions, generate PDF/HTML, publish.

3. **Zero duplicate data entry**
   - Data entered once is reused everywhere (exports, PDFs, website pages).

4. **Version control & audit trail**
   - Track who changed what and when; recover earlier versions where needed.

5. **Dashboards & alerts**
   - Role-specific views of progress, blockers and upcoming tasks, with notifications.

6. **Accessibility & usability**
   - Clear, consistent UI, keyboard-friendly, supports non-English references.

7. **Data quality & integrity**
   - Validation on import (e.g., titles, authors, special characters), required fields at the right steps, duplicate detection and merge tools.

8. **Interoperability**
   - Clean exports (PDF, CSV/Excel, JSON/API) for CE website and reporting.

9. **Open-source & community-driven**
   - Built with open-source tools, extensible by the community, with clear contribution guidelines.
   - Documentation and codebase in a single repository for easy access.
   - Transparent development process with regular updates and community feedback.

## Minimal Viable Product (MVP)

- Protocol drafting + board feedback (basic version history).
- RIS import with validation, de-duplication and (initial) basic screening UI.
- Summary editor with required metadata (action, threat, taxon, habitat, location, research design).
- Review/approval workflow (submit → review → approve/revise).
- Chapter/action assembly page + **one-click PDF** of a sample chapter.
- Manager dashboard with high-level progress and task list.

---

