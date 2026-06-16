# Macro Programming Guide

This guide reflects the current macro system in the codebase.

## Main files

Macro behavior is primarily implemented in:
- `src/monitor/lib/macros.py`
- `src/monitor/lib/macro_utils.py`

## Macro sources and precedence

The current runtime layers macro values in this precedence order:
1. public built-in macros
2. file-defined macros
3. ephemeral runtime macros
4. private built-in macros

Because later updates win, private built-ins have the highest precedence and cannot be overridden by user-defined macros.

## Macro storage

Persistent macros are loaded from the configured macro file, typically `macros.json` under the user config directory.

At startup and reload time, Monitor loads:
- executable macro entries
- optional metadata from reserved keys

Reserved metadata keys currently include:
- `_groups`
- `_macro_meta`

Top-level keys beginning with `_` are treated as metadata, not executable macros.

## Runtime-added macros

Users can add ephemeral macros during a session with:

```text
<key=value
```

These are stored in `EPHEMERAL_MACRO_VALUES` and do not persist across application restarts.

## Default delimiters

The current default delimiter config is:

```yaml
macro_delimiters:
  open: "{{"
  close: "}}"
  escape: "\\"
```

Examples:

```text
<proj=~/projects/monitor
cd {{proj}}
```

## Visible macro catalog and metadata

`macros.py` builds a grouped macro catalog for display.

Display metadata can define:
- macro title
- macro description
- macro usage
- macro group

Group metadata can define:
- title
- description
- order

This grouped catalog is what the `macros` built-in displays.

## Built-in public macros

The current codebase ships public macros such as:
- `do_diff`
- `create_git_entry`
- `rank_examine`
- `diff`
- `diff_previous`
- `xdiff`
- `plan`
- `wdyt`

Private built-ins also exist for internal behavior and are intentionally hidden from normal macro listings.

## Recursive expansion

`recursive_macro_expand(...)` in `macro_utils.py` performs nested macro expansion using the configured delimiters.

The implementation includes:
- delimiter-aware recursive parsing
- escape handling
- cycle/iteration protection
- Tcl macro detection and execution

## Tcl-backed macros

The current macro system supports Tcl execution.

Important security property:
- Tcl macros are executable host-side code
- they are not a sandboxed template format
- they should be treated like trusted local code

The Tcl interpreter is loaded lazily so environments without Tk bindings can still use non-Tcl macros.

## Current Tcl forms

The code recognizes Tcl-style macro content using forms such as:
- `{{tcl ...}}`
- bare leading `tcl ...` in certain paths

The Tcl body is evaluated with a cached `tkinter.Tcl()` interpreter. Macro expansion is not performed inside the Tcl code body itself; the body is executed largely as written after delimiter-literal unescaping.

## Listing macros

The built-in:

```text
macros
```

renders grouped visible macros with metadata-derived headings and descriptions.

It uses a pager when available.

## Editing and reloading

Current related built-ins include:
- `edit_macros`
- `reload_macros`

`edit_macros` opens the configured macro file in the user's editor.

`reload_macros` reloads the macro file into the runtime store.

## Practical examples

### Persistent macro in `macros.json`

```json
{
  "proj": "~/projects/monitor",
  "go_proj": "cd {{proj}}"
}
```

### Runtime macro

```text
<branch_prompt=Summarize the current branch state
```

### Using a macro

```text
{{branch_prompt}}
```

## Contributor guidance

If you change macro behavior, review both:
- `macros.py` for state, precedence, listing, and runtime integration
- `macro_utils.py` for parsing and expansion semantics

Be especially careful with:
- precedence ordering
- recursive expansion termination
- Tcl execution safety
- metadata loading compatibility

## Summary

The current macro system supports:
- persistent JSON-backed macros
- ephemeral session macros
- grouped metadata-driven listings
- nested delimiter-based expansion
- executable Tcl-backed macros for trusted environments
