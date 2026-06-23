# Technical Notes

_Status updated: 21 June 2026 by Ibrahim Alhas._

This document explains how CE Synopsis Portal works at a technical level: the runtime stack, code organization, data model, workflow orchestration, background processing, and the OnlyOffice integration.

If you are tracing behaviour in the code, the usual path is:

1. start in `src/synopsis/urls.py`
2. follow the route into `src/synopsis/views.py`
3. inspect the matching form, model, and template
