# MACROS_README.md

# Macro Programming Guide

This document explains how macros work in this app, with concise, accurate, and runnable examples. It covers pure (string) macros and TCL-backed macros, file locations and defaults, configuration options, built-in commands for editing and reloading macros, and short troubleshooting steps.

## Table of Contents
1. Overview
2. File locations and format
3. Delimiters and escaping
4. Pure macros (string substitution)
5. TCL macros (embedded TCL evaluation)
6. Built-ins: editing, reloading, listing
7. API hooks and tests
8. Troubleshooting

---

## 1. Overview
There are two macro flavors:

- Pure macros: simple string values that may reference other macros using the configured delimiters.
- TCL macros: macro values whose body begins with the token `tcl` (inside the macro delimiters) and which are passed to an embedded TCL interpreter for evaluation. Important: macro references like `(other_macro)` are NOT automatically expanded inside TCL bodies by default. The macro engine only unescapes escaped delimiters inside TCL bodies; it does not perform recursive macro expansion there. If you need macro data inside TCL code, expand it before creating the TCL body or use the programmatic APIs described below.

---

## 2. File locations and format

- Macros are stored in JSON format in `macros.json`.
- Default location: `~/.config/monitor/macros.json`.
- On first run the application will copy the packaged default `macros.json` into that location; see `src/monitor/__main__.py` for the copy-on-first-run behavior.

Example `macros.json` file (JSON):
```
{
  "hello_macro": "Hello, world!",
  "name_macro": "Alex",
  "greet_macro": "Hello, (name_macro)!",
  "math_macro": "(tcl set a 6; set b 3; puts [expr {$a * $b + 2}])",
  "date_macro": "(tcl puts [clock format [clock seconds] -format \"%Y-%m-%d\"])"
}
```

Notes:
- Keys and values must be valid JSON strings.
- TCL macros are represented as strings whose value begins with `(tcl ` and ends with `)` (using the configured delimiters).

---

## 3. Delimiters and escaping

- Default delimiters: `(` and `)`.
- Default escape character: backslash `\`.
- To write a literal delimiter inside macro text or a TCL body you can escape it with `\` (for example `\(` or `\)`).
- Delimiters are configurable via the app configuration `config.yaml` using the `macro_delimiters` setting. Example in `config.yaml`:
```
macro_delimiters:
  open: "("
  close: ")"
  escape: "\\"
```

Behavior summary:
- Pure macro bodies: `(macro_name)` occurrences are expanded by the macro engine.
- TCL macro bodies: the text within `(tcl ... )` is passed largely as is to the embedded TCL interpreter. The macro engine does not perform macro substitutions inside TCL bodies by default; only escaped delimiters are unescaped so the TCL code can contain literal delimiter characters.

---

## 4. Pure macros (string substitution)

Definition example (in JSON):
```
{
  "morning_macro": "Good morning!",
  "user_name": "Alex",
  "greet_user": "Hello, (user_name)!",
  "day": "Wednesday",
  "schedule": "Your meeting is scheduled for (day)."
}
```

Expansions:
- Expanding `(morning_macro)` → `Good morning!`
- Expanding `(greet_user)` → `Hello, Alex!`
- Expanding `(schedule)` → `Your meeting is scheduled for Wednesday.`

Notes:
- Pure macros can nest and reference each other using the configured delimiters.
- Watch for cycles; recursive loops will either be detected or will cause uncontrolled behavior depending on configuration.

---

## 5. TCL macros (embedded TCL evaluation)

TCL macros are executed in an embedded TCL interpreter. The result sent back to the macro system is the output written by `puts` (standard output of the TCL code). TCL macros require the Python build to include Tcl/Tk bindings (usually provided by `tkinter`). If your environment lacks tkinter or Tcl support, TCL macros will not run.

Key points:
- Macro expansion is NOT performed inside TCL bodies by default. If you put `(other_macro)` inside the TCL body, it will be treated as literal text unless you explicitly expand it before creating the TCL macro string.
- The macro engine will unescape escaped delimiters inside TCL bodies to allow literal delimiter characters.
- Use valid TCL syntax. Examples below are runnable TCL code snippets.

Runnable examples (as JSON entries):

Math calculation:
```
"math_macro": "(tcl set a 6; set b 3; puts [expr {$a * $b + 2}])"
```
Expanding `(math_macro)` yields:
```
20
```

Date / time:
```
"date_macro": "(tcl puts [clock format [clock seconds] -format \"%Y-%m-%d\"])"
```
Expanding `(date_macro)` yields (example):
```
2024-06-08
```

Conditional logic (demonstrates using flags from the JSON, but note: references to other macros will not be expanded automatically inside the TCL body):
```
"is_prod": "0",
"show_env": "(tcl if {0 == 1} {puts \"Production\"} else {puts \"Development\"})"
```
Expanding `(show_env)` yields:
```
Development
```

String manipulation:
If you want to operate on a pure macro value inside TCL, do one of:
- Expand the pure macro before the TCL macro is constructed (preferred if the value is static).
- Or pass the data into TCL through an external path your app provides (see API hooks below).

Example (expanding before creating the TCL body):
```
"repeated": "foo   bar   baz",
"squash_spaces": "(tcl set s \"foo   bar   baz\"; regsub -all { +} $s { } result; puts $result)"
```
Expanding `(squash_spaces)` yields:
```
foo bar baz
```

Important: Do not rely on automatic expansion of `(repeated)` inside the TCL string; perform substitution outside the TCL body or use programmatic lookup.

TCL runtime requirements:
- The embedded TCL interpreter is provided by the host via Tcl/Tk (commonly accessible via Python's `tkinter` module). Ensure `tkinter` is available in your runtime environment to use TCL macros.

---

## 6. Built-ins: editing, reloading, listing

Interactive built-in commands available in the app shell:

- Edit macros file:
```
:edit_macros
```
This opens the `macros.json` file in the configured editor (see app settings). On save, changes are not applied until reload.

- Reload macros:
```
:reload_macros
```
This re-reads `~/.config/monitor/macros.json` and updates the runtime macro store.

- List macros:
```
macros
```
(or the equivalent built-in command named `macros`) — lists known macros and their current expansion results (pure expansions shown; TCL macros may show a short indicator of being TCL-backed).

Examples:
- Run `:edit_macros` to modify your JSON file.
- Then run `:reload_macros` to apply your changes without restarting the whole application.
- Run `macros` to see the current macro definitions.

---

## 7. API hooks and tests

Programmatic helpers you may use or inspect:
- `load_additional_macros` in `src/monitor/lib/macro_utils.py`: helper to load extra macro definitions into the runtime store.
- `update_macros` in `src/monitor/lib/macro_utils.py`: helper to replace or merge macro definitions at runtime.

See the implementation and unit tests for examples and expected behaviors:
- Implementation: `src/monitor/lib/macro_utils.py`
- Tests: `tests/test_macro_utils.py`

These show canonical usage patterns, edge cases, and how the macro engine treats TCL bodies and delimiter escaping.

---

## 8. Troubleshooting (short)

- TCL macros produce `[TCL ERROR: ...]` in the expansion:
  - Check your TCL syntax in the macro value.
  - Ensure `tkinter` / Tcl bindings are available in your Python runtime.
  - Run the TCL body in a standalone TCL interpreter to validate.

- Empty or placeholder TCL bodies:
  - `(tcl )` or `(tcl ...)` with no `puts` output will expand to an empty string. Add a `puts` to emit the desired text.

- Delimiter problems:
  - If your macro text contains delimiter characters, escape them with the configured escape character (default `\`).
  - Verify `config.yaml` `macro_delimiters` if you have nonstandard delimiters.

- JSON errors:
  - Invalid `macros.json` (malformed JSON) will prevent the file from loading. Use a JSON validator and ensure proper quoting/escaping.

- Need to use a macro value inside TCL:
  - Expand the value before embedding it in the TCL macro string, or use the APIs in `macro_utils.py` to provide data to the TCL environment. Do not assume automatic in-TCL macro expansion.

---

For more advanced examples and the authoritative code for macro handling, consult:
- `src/monitor/__main__.py` (copy-on-first-run behavior and default file location)
- `src/monitor/lib/macro_utils.py` (loading/updating macros and helpers)
- `tests/test_macro_utils.py` (unit tests demonstrating expected behaviors)

End of guide.
