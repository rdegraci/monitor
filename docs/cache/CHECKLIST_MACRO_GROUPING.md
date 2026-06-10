# Macro Grouping Checklist

## Design
- [x] Confirm private macros remain hidden in standard macro display.
- [x] Confirm normal display shows only effective visible macros after precedence is applied.
- [x] Confirm fallback metadata behavior for unannotated macros.
- [x] Confirm initial group taxonomy.

## `macros.json` Format
- [x] Add reserved metadata sections for `_groups` and `_macro_meta`.
- [x] Keep executable macro definitions as top-level flat string entries.
- [x] Preserve compatibility with metadata-free flat macro files.

## Loading and Parsing
- [x] Identify the macro file loading entry point in `src/monitor/lib/macro_utils.py`.
- [x] Refactor executable macro loading to exclude underscore-prefixed metadata keys.
- [x] Add a metadata parsing path for `_groups` and `_macro_meta`.
- [x] Validate behavior for malformed metadata blocks.

## Built-in Metadata
- [x] Add metadata for `PUBLIC_MACRO_VALUES` entries.
- [x] Add metadata for `PRIVATE_MACRO_VALUES` entries if needed for internal catalog use.
- [x] Define built-in group metadata for hard-coded macros.
- [x] Add a default runtime group for `EPHEMERAL_MACRO_VALUES`.

## Catalog Builder
- [x] Create a unified macro descriptor model for display.
- [x] Merge JSON-defined and hard-coded macro metadata into one catalog.
- [x] Apply runtime-equivalent precedence when resolving duplicate macro names.
- [x] Exclude private macros from standard display output.
- [x] Add fallback values for missing title, description, and group.

## Display
- [x] Refactor `print_macros()` to use the unified catalog.
- [x] Render grouped sections with group title and description.
- [x] Render each macro with name, title, and description.
- [x] Render optional `usage` text for macros that take arguments.
- [x] Use ANSI coloring for macro names and usage lines.
- [x] Ensure output remains pager-friendly.
- [x] Preserve colored output through the pager by setting `LESS=-R` during paging.

## Tests
- [x] Add tests for executable macro loading with metadata sections present.
- [x] Add tests for backward compatibility with legacy flat `macros.json`.
- [x] Add tests for precedence preservation.
- [x] Add tests for grouped catalog creation.
- [x] Add tests for fallback metadata behavior.
- [x] Add tests ensuring private macros remain hidden by default.
- [x] Add tests for grouped display rendering.
- [x] Add tests for file-defined group metadata overrides.
- [x] Add tests for `usage` metadata in the visible catalog.
- [x] Add tests for ANSI-safe pager environment handling.

## Documentation
- [x] Document the new `macros.json` metadata structure.
- [x] Document fallback behavior for unannotated macros.
- [x] Document visibility rules for public, file, runtime, and private macros.
- [x] Document precedence and override behavior in grouped display.
- [x] Document optional `usage` metadata for command-style macros.
- [x] Document pager behavior needed for ANSI-colored grouped output.

## Validation
- [x] Verify macro expansion behavior is unchanged.
- [x] Verify macro precedence is unchanged.
- [x] Verify grouped display works when metadata is partially populated.
- [x] Verify grouped display works when no metadata exists.
- [x] Verify file-provided group headings override built-in fallback headings.
- [x] Verify grouped display preserves ANSI coloring when paged.
