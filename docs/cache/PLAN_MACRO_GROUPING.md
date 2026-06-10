# Macro Grouping Plan

## Objective
Add grouped macro display with group titles, group descriptions, per-macro titles, descriptions, and optional usage text while preserving current macro execution behavior and precedence.

## Status
Implemented in the current branch.

Delivered behavior now includes:
- reserved display metadata sections in `macros.json` via `_groups` and `_macro_meta`
- filtering of underscore-prefixed metadata keys out of executable macro loading
- built-in metadata for public and private hard-coded macros
- a unified visible macro catalog for display across built-in, file, and runtime sources
- grouped rendering in `print_macros()`
- fallback metadata for unannotated macros and groups
- support for per-macro `usage` text in grouped display
- pager-friendly ANSI output by temporarily setting `LESS=-R`

## Current State
The macro runtime composes effective macro values from multiple sources in `src/monitor/lib/macros.py` via `configure_macros()`:

1. `PUBLIC_MACRO_VALUES`
2. file macros from `macros.json`
3. `EPHEMERAL_MACRO_VALUES`
4. `PRIVATE_MACRO_VALUES`

The current display path in `print_macros()` does not render the merged runtime dictionary. It prints visible macro sources separately and omits private macros.

## Key Constraints
- Do not break existing macro expansion behavior.
- Do not change macro precedence.
- Do not require nested runtime macro structures.
- Preserve compatibility with existing flat `macros.json` files.
- Treat private macros as hidden by default unless intentionally exposed later.

## Proposed Design

### 1. Keep execution flat
Continue to represent executable macros as a flat `dict[str, str]` for runtime expansion.

### 2. Add display-only metadata
Add optional metadata for grouping, descriptions, and usage text without mixing metadata into the expansion dictionary.

Recommended JSON metadata sections:
- `_groups`
- `_macro_meta`

Example shape:

```json
{
  "_trust_model": "...",
  "_groups": {
    "git": {
      "title": "Git",
      "description": "Repository, branch, and commit helper macros."
    }
  },
  "_macro_meta": {
    "branch": {
      "group": "git",
      "title": "Current branch",
      "description": "Print the current git branch name."
    }
  },
  "branch": "{{tcl ...}}"
}
```

### 3. Filter metadata from executable macro loading
Refactor macro file loading so metadata keys such as `_groups` and `_macro_meta` are not merged into `MACRO_VALUES`.

### 4. Add built-in metadata in code
Add parallel metadata dictionaries for hard-coded macros so both JSON-defined and source-defined macros can be grouped consistently.

Potential structures:
- `PUBLIC_MACRO_METADATA`
- `PRIVATE_MACRO_METADATA`
- shared group metadata registry for built-in groups

### 5. Build a unified macro catalog for display
Normalize all visible macro sources into a common descriptor shape for presentation.

Suggested descriptor fields:
- `name`
- `value`
- `group`
- `title`
- `description`
- `usage`
- `source`

### 6. Preserve precedence in catalog resolution
The grouped display should reflect the same winner selection as runtime macro expansion:
- public < file < ephemeral < private

Normal display should show the effective visible macro entry, not all overridden variants.

### 7. Keep private macros hidden by default
Continue excluding `PRIVATE_MACRO_VALUES` from standard macro display.

### 8. Replace JSON dump display with grouped rendering
Refactor `print_macros()` to render grouped sections with:
- group title
- group description
- macro title
- macro description
- optional usage text
- ANSI-safe pager output for colored macro names and usage lines

### 9. Support fallback behavior
For macros without metadata:
- group = `ungrouped`
- title = macro name
- description = empty string

For groups without explicit metadata:
- title = group id
- description = empty string

## Suggested Grouping Buckets
Based on the current macro set, likely groups include:
- `analysis`
- `git`
- `system`
- `python`
- `ios`
- `runtime`
- `ungrouped`

## Testing Strategy
Add tests for:
- filtering metadata keys out of executable macro loading
- preserving runtime precedence
- backward compatibility with old flat `macros.json`
- grouped catalog creation
- fallback metadata behavior
- hidden private macro behavior
- grouped display output

## Rollout Sequence
1. Add metadata parsing support.
2. Filter metadata out of executable macro loading.
3. Add built-in macro metadata in code.
4. Implement unified catalog builder.
5. Refactor `print_macros()` to grouped rendering.
6. Add and update tests.
7. Annotate `macros.json` with group and macro metadata.
8. Extend grouped display with `usage` metadata and ANSI-safe pager support.

## Risks
- Accidentally treating metadata blocks as executable macros.
- Divergence between runtime precedence and display precedence.
- Displaying hidden/private macros unintentionally.
- Breaking compatibility with old flat macro files.

## Success Criteria
- Existing macros continue to execute exactly as before.
- Existing flat `macros.json` remains valid.
- Display shows visible macros in logical groups.
- Group titles and descriptions render correctly.
- Per-macro titles and descriptions render correctly.
- Private macros remain hidden in normal display.
