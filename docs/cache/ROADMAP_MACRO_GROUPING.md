# Macro Grouping Roadmap

## Status
Core roadmap items are implemented in the current branch. The roadmap below is retained as a record of what was delivered and what the implementation now supports.

## Phase 1: Schema and Compatibility
Define the metadata model for grouped display, descriptions, and usage text without changing runtime macro expansion.

### Deliverables
- display metadata schema for groups and macros
- compatibility rules for legacy flat `macros.json`
- fallback behavior for missing metadata
- optional per-macro `usage` metadata for command-style macros

### Outcome
A stable contract exists for grouping data before implementation details are changed.

## Phase 2: File Parsing Separation
Separate executable macro loading from display metadata loading.

### Deliverables
- executable macro loader that ignores reserved metadata keys
- metadata loader for `_groups` and `_macro_meta`
- tests for mixed executable and metadata content in `macros.json`

### Outcome
`macros.json` can safely contain grouping metadata without affecting runtime expansion.

## Phase 3: Built-in Metadata Coverage
Introduce metadata for hard-coded macros defined in source code.

### Deliverables
- metadata structures for `PUBLIC_MACRO_VALUES`
- metadata structures for `PRIVATE_MACRO_VALUES` if useful internally
- built-in group registry
- runtime group metadata for ephemeral macros

### Outcome
All macro sources can participate in a unified grouped display model.

## Phase 4: Unified Catalog Builder
Create a display-layer catalog that merges macros and metadata across sources.

### Deliverables
- normalized macro descriptor model
- precedence-aware merge logic for display
- visibility filtering for hidden/private macros

### Outcome
The application has one source of truth for rendering macro help and listings.

## Phase 5: Grouped Rendering
Refactor macro listing output to render logical sections instead of raw JSON dumps.

### Deliverables
- grouped `print_macros()` implementation
- group title and description rendering
- per-macro title and description rendering
- per-macro usage rendering where available
- stable sort order for groups and macros
- ANSI-safe pager behavior so colored output survives paging

### Outcome
Users can browse macros by logical category with richer descriptions and usage guidance.

## Phase 6: Annotation and Migration
Incrementally enrich `macros.json` and built-in macro metadata.

### Deliverables
- initial group metadata population
- initial per-macro metadata population
- explicit group assignment for file-defined macros
- fallback handling for unannotated entries

### Outcome
The grouped display becomes useful immediately and improves as metadata coverage grows.

## Phase 7: Hardening and Documentation
Validate behavior and document the format.

### Deliverables
- regression tests for runtime behavior
- display tests for grouped output
- documentation for the metadata format and visibility rules

### Outcome
The feature is maintainable, backwards-compatible, and understandable to users and developers.

## Guiding Principles
- Preserve runtime execution semantics.
- Preserve precedence semantics.
- Keep metadata separate from executable macro values.
- Make legacy configurations continue to work.
- Keep hidden/private macros hidden by default.
