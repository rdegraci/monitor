# MONITOR_CONVENTIONS.md

This is the **global fallback** loaded when the startup directory has no project-local `MONITOR_CONVENTIONS.md`. Resolution order at startup: `<cwd>/MONITOR_CONVENTIONS.md` → `<cwd>/build/MONITOR_CONVENTIONS.md` → this packaged copy (via `appdir/monitor/MONITOR_CONVENTIONS.md`). The `build/` fallback lets a build pipeline generate a project-specific copy without touching the repo root. The path is read once at startup and frozen for the session — `:cd` later does not re-resolve.

## Language-agnostic change hygiene

- **Run the existing tests** before reporting a change as complete. If a test suite exists and you didn't run it, say so explicitly.
- **Use the project's installed tooling.** If `pyproject.toml` configures ruff/mypy/pytest, or the Xcode project has SwiftLint/SwiftFormat, use those — don't introduce new ones.
- **Match the existing style.** Import order, naming case (camelCase / snake_case / PascalCase), indent width, brace/wrap conventions, error-handling pattern — read a few neighboring files first and follow them.
- **Don't add dependencies without confirming.** New libraries shift the lockfile and the project's supply chain; mention it before running an install.
- **Preserve trailing newlines and line endings.** EOL conversions and stripped trailing newlines make diffs harder to review for no benefit.
- **Keep diffs minimal.** Don't reformat code that wasn't part of the task; don't reorder imports unless that's the task.
- **For multi-file changes, list the affected files first** so the user can scope-check before edits land.

## Swift conventions

**Logging.** When editing Swift files:
1. `logger.trace()` — function entry/exit, significant internal state snapshots, rare diagnostic details. Keep sparse.
2. `logger.info()` — important runtime state changes, completed major tasks, configuration or lifecycle events.
3. `logger.warning()` — recoverable or soft errors.
4. Never use `logger.debug()` or `logger.error()` — those are reserved for human developers.
5. Don't add logs in hot loops or for trivial local values.
6. At most one additional log per changed function unless necessary.

Use Swift string interpolation, not printf-style placeholders:
- Good: `logger.trace("Entering parseInput, id=\(userId)")`, `logger.info("Service started on port \(port)")`
- Avoid: `logger.trace("Entering parseInput, id=%s", userId)` (printf style is wrong for Swift)

**Code conventions:**
- Concurrency: respect existing actor isolation. Don't add `@MainActor` without checking how the function is called; don't strip it without the same check. Be careful with `async` boundaries when refactoring synchronous code.
- Errors: prefer `throws` / `Result` over `NSError` callbacks in new code, but match what the surrounding module does.
- Optionals: prefer `if let` / `guard let` over force-unwrap (`!`) except where the invariant is genuinely unbreakable and obvious.
- Access control: prefer the narrowest visibility that still works (`private` > `fileprivate` > `internal`); don't widen visibility just to make a test reach a symbol — restructure or test through the public surface instead.
- Don't edit the Xcode project file (`*.pbxproj`) by hand. If a file needs adding to the project, surface it so the user can do it in Xcode, or use the proper SPM/xcodebuild tooling.
- SwiftUI and UIKit: don't mix paradigms within one type unless the file already does.

## Python conventions

**Logging.** When editing Python files:
1. `logger.info()` — important runtime state changes, completed major tasks, configuration or lifecycle events.
2. `logger.warning()` — recoverable or soft errors.
3. Never use `logger.debug()` or `logger.error()` — reserved for human developers (matches the Swift convention).
4. Use lazy formatting: `logger.info("Service started on port %s", port)`, not `logger.info(f"Service started on port {port}")` — the lazy form skips the string interpolation when the log level is filtered out.
5. Don't add logs in hot loops or for trivial local values.
6. At most one additional log per changed function unless necessary.

**Code conventions:**
- Type hints: match the project's posture. If the codebase uses type hints, add them to new code; if it doesn't, don't introduce them in unrelated edits.
- Imports: follow whatever ordering the project uses. If `ruff` or `isort` is configured, let it sort — don't reorder by hand.
- CLI library: use the one the project already uses (`argparse`, `click`, `typer`). Don't introduce a new one in a focused change.
- Exceptions: catch the specific exception class, not bare `Exception`.
- String formatting: f-strings vs `.format()` vs `%` — match the surrounding code.
- Don't pin dependency versions unilaterally; defer to the project's lockfile/uv/pip-tools workflow.
- Don't add `if __name__ == "__main__":` blocks to library modules; keep entry points in dedicated scripts or `__main__.py`.
