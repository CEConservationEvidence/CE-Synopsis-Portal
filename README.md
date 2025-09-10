# CE Synopsis Portal*

_*Working title — final name to be agreed with the Conservation Evidence (CE) team._

A unified, open-source workspace to **plan, search, screen, summarise, review, assemble, and publish** Conservation Evidence synopses — with one source of truth, clear roles, and minimal copy–paste. This repository is self-contained and houses both the documentation and the codebase.

---

TODO: cleanup and reorganize readme.md content.

## Getting Started

TODO: WIP.

- [Installation](./installation.md)
- [Quick Start Guide](./quick-start.md)

## Features

TODO: WIP.

- [Features](./features.md) (drafting)
- [Roadmap](./docs/roadmap.md/) (done)

## Documentation

TODO: WIP.

- [User Guide](./user-guide/index.md) (for end users)
- [API Reference](./api/index.md)
- [Tutorials](./tutorials/index.md)
- [FAQ](./faq.md)

## Purpose & Users

**This system is being built originally for the Conservation Evidence team, but may be adopted by other related teams in the future.**

Create a single, central tool that replaces scattered Word/Excel files and manual CMS steps. This tool will (eventually) make it **faster, clearer, and less error‑prone** for the CE team to produce synopses, while remaining flexible enough to reuse for other “living evidence” topics. 

- **Authors** – import/search, screen, write approx. 200-word summaries, tag studies, update records and metadata on website for public consumption.
- **Project Manager** – draft synopsis protocol document, invite advisory board members, oversee synopsis and team progress, review/approve, manage timelines.
- **Data Manager** – manage imports, vocabularies, consistency checks (role will likely become redundant).
- **Advisory Board** – accepts official invitation to participate in a synopsis, view protocols, comment on scope/actions; provide their input directly on the draft synopsis document.

---

## Core Expectations (high‑level, v1, subject to change)

1. **Single source of truth**
   - All references, summaries, tags, backgrounds, key messages, actions, and search logs live in the database.
   - No hard-coded domain lists (e.g., species); use editable controlled vocabularies.

2. **End-to-end workflow**
   - Plan & protocol: draft, version, share with the board.
   - Import & screen: ingest RIS, detect duplicates, include/exclude with reasons; update database efficiently.
   - Summarise & tag: rich editor with approx. 200‑word guardrails and structured fields.
   - Review & approve: role‑based workflows, comments, change requests and final approval.
   - Assemble & publish: compile chapters/actions systematically, generate final synopsis PDF document, publish to main CE Website.
   - Automatically upload synopsis-related data to CE website via API integration, bypassing manual copy and pasting of data by authors.

3. **Zero duplicate data entry**
   - Data entered once is reused everywhere (exports, PDFs, website, etc.).

4. **Version control & audit trail**
   - Track who changed what and when; recover earlier versions where needed (and handle database migrations).

5. **Dashboards & alerts**
   - Role-specific views of progress, blockers and upcoming tasks, with notifications. A clean and informative dashboard for each role.

6. **Accessibility & usability**
   - Clear, consistent UI, keyboard-friendly, supports non-English references.

7. **Data quality & integrity**
   - Validation on import (e.g., titles, authors, special characters), required fields at the right steps, duplicate detection, and merge tools.

8. **Interoperability**
   - Clean exports (PDF, CSV/Excel, JSON/API) for CE website and reporting.

9. **Open-source & community-driven**
   - Built with open‑source tools, extensible by the community, with clear contribution guidelines.
   - Documentation and codebase in a single repository for easy access.
   - Transparent development process with regular updates and community feedback.
  
10. **Scalability & maintainability**
    - Modular architecture to support future features (e.g., advanced search, AI‑assisted tagging).
    - Clear code structure, documentation, and testing to ensure long‑term sustainability, with a focus on reducing technical debt.

11. **Security & privacy**
    - Secure user authentication and role-based access control.

12. **Offline Support (TBD)**
    - Basic functionality available without an internet connection.

## Minimum Viable Product (MVP)

- Protocol drafting + board feedback (basic version history).
- RIS import with validation, de-duplication and (initial) basic screening UI.
- Summary editor with required metadata for CE (action, threat, taxon, species, habitat, location, research design).
- Review/approval workflow (submit → review → approve/revise) with authors and synopsis manager.
- Chapter/action assembly page + one-click PDF of final synopsis document for website upload.
- Manager dashboard with high-level progress and task list.
- Automatic synopsis data upload to CE website via API integration.
- Comprehensive testing and validation of all features, as well as documentation and user guides.

---

## Ultimate Outcome (what “good” looks like to the CE team)

- **A single, reliable platform** used by the CE team for all new synopses.
- **No manual copy–paste** to build the final PDF or website entries.
- **Consistent summaries and tags**, enforceable by templates and vocabularies.
- **Clear accountability** via roles, reviews, and auditable history.
- **Portable design** that can be reused for other “living evidence” domains.
- **Easy‑to‑use interface** enabled by sound UI/UX design and implementation choices.
- **Open‑source codebase** that the community can contribute to and extend.

## Roles & Permissions

Note: This is a first draft and will be refined with the CE team.
- **Author**: create/edit summaries; propose tags; submit for review.
- **CE Manager**: approve/reject; edit; assign tasks; see all dashboards.
- **Data Manager**: manage imports; vocabularies; data validation (this role will become redundant as automation is implemented).
- **Advisory Board**: comment/approve protocol and actions; read-only summaries.
- **Admin**: user management; configuration; environment settings.
- **External Guest**: to be defined, likely read-only access to specific summaries or protocols.

## Technical Stack

This project is built entirely with open-source, mature, and well-supported tools designed to be maintainable, secure, and easy to contribute to. Note that 'x' for version numbers indicates the latest compatible release.

### Main
- **Python 3.12.x+**
  - Modern and widely supported programming language.
  - All backend logic is written in Python.

- **Django 5.2.x (LTS)**
  - Core backend framework.
  - Handles user permissions, data models, workflows, and the admin dashboard.
  - Long-Term Support release with stability until at least April 2026.

- **PostgreSQL 15**
  - Robust, relational database system.
  - Stores all data including references, summaries, tags, workflows, and users.
  - Chosen for reliability, scalability, and Django compatibility.

- **Django REST Framework 5.2.x (LTS)**
  - Used to expose data through a clean, maintainable JSON API.
  - Allows the CE website to pull public data directly (e.g. summaries, chapters).

- **Celery 5.5.x & Redis 6.4.x**
  - Task queue system for background jobs.
  - Used for long-running tasks like RIS file imports, PDF generation, and data exports.

- **WeasyPrint 66.x**
  - Converts final synopses (HTML) into high-quality PDFs for uploading to main CE Website.
  - Converts the Synopsis Protocol documents into a high-quality PDF for uploading to main CE Website, namely the Synopses page (under 'View protocols for upcoming synopses').
  - Supports custom styling, date stamps, and inclusion of advisory board info.

- **Wagtail 6.3.x (LTS)**
  - Rich-text editing layer for authors, including support for templates and custom styling.
  - Provides a user-friendly interface for narrative sections like protocols, backgrounds."
  - Used internally — not for rendering the public site (however, it may possibly replace the current main CE website later so there is potential for public use).

- **psycopg 3.2.x**
  - PostgreSQL driver used by Django to connect to the database.

### Development & Maintenance
- **GitHub**
  - Used for version control, collaboration, and issue tracking.
  - GitHub Actions for CI/CD pipelines.
  - GitHub Pages for documentation hosting.
  - GitHub Discussions for community engagement and support.

- **Docker**
  - Standardises development and deployment environments.
  - Will just run Postgres, Redis, and the Django app with a single command.
  - Simplifies the setup process for new developers and collaborators.

## Roadmap

Roadmap - see `docs/roadmap.md` for details.

## License

MIT License — see `LICENSE` for details.

## Acknowledgements

Maintainer and main developer: **Ibrahim Alhas** (alhasacademy@gmail.com).

---

# Contributing

Please read the [Contributing Guidelines](CONTRIBUTING.md) before making a pull request.
