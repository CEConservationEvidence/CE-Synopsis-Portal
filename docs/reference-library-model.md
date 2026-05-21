# Reference Library Model

Status updated: 20 May 2026

This note defines how the shared reference library and synopsis-level references are intended to work together.

## Core model

The portal does not need two separate reference databases. It needs one shared canonical library plus synopsis-level working copies.

### Global shared record

`LibraryReference` is the canonical CE record for a paper.

It should hold data that is true regardless of synopsis:
- citation metadata
- DOI / URL
- shared CE subject categories
- library-level import provenance
- shared document/PDF metadata where applicable

There should be one global library record per paper.

### Synopsis/project record

`Reference` is the synopsis-level working record linked to a project.

It should hold data that is specific to one synopsis:
- screening status
- screening notes
- who screened the reference
- summary tabs
- synopsis assignments
- full-text exclusion reasoning
- synopsis-specific comments and workflow state

## How authors use the system

Authors should mostly work from inside a synopsis.

There are two main entry routes:

1. Upload into a synopsis
   - the system parses the upload
   - it reuses an existing `LibraryReference` if one already exists
   - otherwise it creates a new `LibraryReference`
   - it then creates a synopsis-level `Reference` linked to that library record

2. Link from the shared reference library
   - the system keeps the existing `LibraryReference`
   - it creates a synopsis-level `Reference` linked to that library record

In both cases the synopsis receives its own working copy for screening and summary writing, while the shared library remains the canonical source for shared reference metadata.

## Categories

CE subject categories are reference-level CE metadata, not synopsis-specific workflow state.

The intended rule is:

- categories belong to the shared `LibraryReference`
- linked synopsis references should read those categories from the shared library record
- if an author edits categories while screening or from reference management, that edit should update the shared library record
- any other linked synopsis copies should then reflect the same categories

## Implementation

The current codebase makes the source of truth explicit:

- `LibraryReference.reference_folder` is the authoritative record for linked references
- `Reference.unlinked_reference_folder` is a fallback used only for project references that are not linked to the shared library
- synopsis-specific workflow state stays on `Reference`

Unlinked project references still need a local category value because older imports or development data may not yet have a reliable canonical library link.

## Current implementation status

The code now treats linked references as library-authoritative for category reads:

- `LibraryReference.category_values` normalises the shared category list
- `Reference.category_values` returns the linked library categories when `library_reference_id` is present
- `Reference.category_values` returns `Reference.unlinked_reference_folder` only when the project reference is unlinked
- `Reference.folder_labels()` is based on those effective category values
- screening and summary reference-management writes go through a shared update helper
- author-facing screening and summary pages display the effective shared categories

## Audit result

Remaining direct category field use falls into these groups:

- form field names and POST payloads, which still use `reference_folder` because changing the HTML/API field name would be a larger compatibility change
- `LibraryReference.reference_folder`, which stores the shared categories
- `Reference.unlinked_reference_folder`, which stores local fallback categories only for unlinked project references
- migrations and history models

No author-facing read path should use `Reference.unlinked_reference_folder` for linked references. Use `Reference.category_values` or `Reference.folder_labels()` instead.

## Schema migration path

The final schema-level cleanup should happen in stages:

1. Ensure every project `Reference` is linked to a `LibraryReference` where possible.
2. Run the category audit command to report unlinked project references and legacy linked fallback values.
3. Move exports, reports, and any remaining read paths to `Reference.category_values`.
4. Once unlinked references are either eliminated or explicitly supported long term, decide whether to keep or remove `Reference.unlinked_reference_folder`.

Do not remove `Reference.unlinked_reference_folder` until the project has a migration and rollback plan for old project references that are not linked to the shared library.

## Audit command

Use the category audit command to check whether project references are aligned with the shared library:

```bash
python src/manage.py audit_reference_categories
```

This reports:
- project references with no linked `LibraryReference`
- linked project references that still have legacy local fallback categories

To clear legacy local fallback categories from linked references:

```bash
python src/manage.py audit_reference_categories --clear-linked-local-categories
```

The clear mode updates only linked project references. It does not try to create missing `LibraryReference` links for unlinked project references, because that requires a separate duplicate-matching review.

Optional flags:

```bash
python src/manage.py audit_reference_categories --project-id 12 --limit 50
```

Run this after large imports, migration work, or any future refactor that touches reference linking.

## Practical rules for developers

When working on reference/category code:

- treat `LibraryReference.reference_folder` as the source of truth for linked references
- do not add read paths that prefer `Reference.unlinked_reference_folder` when `library_reference_id` is present
- when categories are edited from a synopsis workflow, update the shared library record for linked references
- when categories are edited on an unlinked project reference, update `Reference.unlinked_reference_folder`
- keep screening status and screening notes strictly synopsis-specific

## Remaining cleanup

The full end-state would be:

- all linked-reference category reads go through the canonical library record
- unlinked project references are either linked into the shared library or explicitly supported as local-only records
- eventually, the local fallback field can be reduced further or removed after a dedicated schema migration

That final step should be treated as a separate refactor because it affects data migration, queries, forms, exports, and older project references that may not yet be library-linked.
