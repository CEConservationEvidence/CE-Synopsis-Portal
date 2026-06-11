# Contributing Guidelines

Hello stranger!

Thank you for considering contributing to Conservation Evidence!

We welcome all kinds of contributions — bug reports, feature requests, documentation improvements, tests, and code.

**Please take a moment to read these guidelines before submitting an issue or pull request.**

---

## First Things First
- Please read the [README](README.md) for setup instructions and project overview.
- Then, please read the technical documentation in the [project wiki](https://deepwiki.com/CEConservationEvidence/CE-Synopsis-Portal/1-overview) for a deeper understanding of the system’s architecture and design rationale. This will help you make informed contributions that align with the project’s goals and standards.

## Reporting Issues
- Before opening a new issue, **search the issue tracker** to see if it’s already reported.  
- Use the **issue template** (already provided) to ensure we get all necessary details.  
- Be clear and provide:
  - Steps to reproduce
  - Expected vs actual behavior
  - Environment details (OS, version, etc.)
  - Screenshots/logs if helpful

---

## Suggesting Features
- Open a **feature request issue** using the template.  
- Clearly explain the problem your feature would solve.  
- If possible, suggest implementation ideas or examples.

---

## Contributing Code

### Getting Started
1. Fork the repository and clone your fork.  
2. Create a new branch:  
   ```bash
   git checkout -b feature/my-feature
   ```
3. Make your changes following our [code style](#-code-style).  
4. Commit with a clear message:  
   ```bash
   git commit -m "Add feature X that does Y"
   ```
5. Push to your fork and open a pull request.

### Pull Request Checklist
- Fill out the **PR template** fully.  
- Keep PRs focused — small, self-contained changes are easier to review.  
- Update or add tests where appropriate.  
- Update documentation if behavior changes.  
- Ensure all checks (CI/tests) pass before requesting review.  

---

## Code Style
- Follow the style already used in the surrounding Django app. Prefer clear, explicit code over clever abstractions, and keep changes scoped to the workflow you are touching.
- Use descriptive names for models, forms, views, templates, and helper functions. Keep workflow terms consistent with the product language used in the UI: projects, protocols, action lists, advisory board members, references, summaries, and synopsis content.
- Keep Django views and forms readable by extracting shared behavior into helpers or service modules when it avoids real duplication. Do not move code just to create more files.
- Add short module docstrings for new Python modules, and add comments only where the intent would otherwise be hard to recover from the code.
- Keep templates organized by workflow under `src/templates/synopsis/`. Shared partials belong under `src/templates/synopsis/includes/<workflow>/`.
- In templates, keep presentation logic light. Put non-trivial business rules in Python code, and use template tags only for small display helpers.
- Avoid unrelated formatting churn. If a file does not already have broad formatting changes, keep the diff focused on the behavior or documentation you are changing.

---

## Testing
- Run the standard Django checks before submitting code:
  ```bash
  cd src
  python manage.py check
  python manage.py test
  ```
- Add or update tests when changing behavior, permissions, data validation, imports/exports, email delivery, reminder scheduling, document workflows, reference handling, or synopsis compilation.
- Use focused unit tests for pure helpers, model methods, form validation, parsing, formatting, and permission predicates.
- Use Django integration tests for views, workflows, database state changes, redirects, template rendering, emails, management commands, and Celery task entry points.
- Add UI regression coverage or clear manual verification notes when changing complex templates, multi-step screens, collaborative document flows, or JavaScript-heavy interactions.
- For documentation-only or comment-only changes, tests are usually not needed, but the PR should say that explicitly.
- PRs without relevant tests may not be accepted unless they’re doc-only.

---

## License
By contributing, you agree that your contributions will be licensed under the same license as this project (see [LICENSE](LICENSE)).  

---

## Questions?
- Check the [README](README.md) for setup instructions.  
- If you’re unsure, feel free to open a draft PR and ask for feedback!  

*We’re excited to collaborate with you. Thank you for helping improve this project.*
