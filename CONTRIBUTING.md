# Contributing Guidelines

Contributions are welcome across bugs, documentation, tests, and feature work. Keep changes technically grounded in the current codebase rather than older planning notes or assumptions.

## Read This First

Start with the repo-local docs:
- [README.md](README.md) for setup and an accurate feature summary
- [docs/instructions.md](docs/instructions.md) for the Docker deployment model
- [docs/reference-library-model.md](docs/reference-library-model.md) for the shared library vs project-reference design
- [docs/roadmap.md](docs/roadmap.md) for the current gap list

The [project wiki](https://deepwiki.com/CEConservationEvidence/CE-Synopsis-Portal/1-overview) is useful for background and rationale, but it is secondary to the repository itself and may lag behind the code.

## Reporting Issues

- Search existing issues first.
- Use the provided issue template.
- Include:
  - steps to reproduce
  - expected vs actual behavior
  - environment details
  - screenshots, logs, or example files when relevant

## Suggesting Features

- Open a feature request issue.
- Explain the problem first, then the proposed change.
- Call out any workflow impact on managers, authors, external authors, or advisory board members.

## Local Workflow

1. Fork the repository and clone your fork.
2. Create a focused branch.
   ```bash
   git checkout -b feature/my-change
   ```
3. Set up the app using the [README](README.md).
4. Make the smallest coherent change that solves the problem.
5. Run checks/tests relevant to the area you changed.
6. Open a pull request with a clear problem statement and verification notes.

## Documentation Standard

Documentation changes should be verified against the current code, env templates, and templates/views that users actually see.

If your change affects:
- environment variables, update the relevant `.env` template files and [docs/instructions.md](docs/instructions.md)
- setup or developer workflow, update [README.md](README.md)
- reference-library behavior, update [docs/reference-library-model.md](docs/reference-library-model.md)
- current scope or open gaps, update [docs/roadmap.md](docs/roadmap.md)

## Code Style

- Follow the surrounding Django style. Prefer clear, explicit code over clever abstractions.
- Keep workflow terms consistent with the UI and data model: projects, protocols, action lists, advisory board members, references, summaries, and synopsis content.
- Extract helpers or service functions when they remove real duplication or clarify a workflow boundary.
- Add short module docstrings for new Python modules.
- Add comments only where the intent would otherwise be hard to recover from the code.
- Keep templates organized under `src/templates/synopsis/` by workflow. Shared partials belong under `src/templates/synopsis/includes/<workflow>/`.
- Keep business rules in Python rather than templates where practical.
- Avoid unrelated formatting churn.

## Testing

Run the standard checks before submitting code:

```bash
cd src
python manage.py check
python manage.py test
```

Notes:
- the test suite expects PostgreSQL test-database access
- documentation-only changes usually do not need tests, but say so explicitly in the PR

Add or update tests when changing:
- permissions or roles
- imports, deduplication, or reference linking
- screening and summary workflows
- synopsis compilation or export
- advisory workflows, reminders, or email delivery
- collaborative editing / OnlyOffice behavior
- management commands or Celery task entry points

Prefer:
- focused unit tests for helpers, parsing, formatting, and validation
- Django integration tests for views, DB changes, redirects, emails, and workflow state

## Pull Requests

- Fill out the PR template.
- Keep PRs scoped and reviewable.
- Include manual verification notes for UI-heavy changes.
- Update documentation when behavior changes.
- Call out any known risk, migration concern, or follow-up work.

## License

By contributing, you agree that your contributions will be licensed under the project license in [LICENSE](LICENSE).

By Ibrahim Alhas, 2025-2026.