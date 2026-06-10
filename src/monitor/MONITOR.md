# MONITOR.md

This is the **global fallback** loaded when the startup directory has no project-local override. Resolution order at startup: `<cwd>/MONITOR.md` → `<cwd>/build/MONITOR.md` → `<cwd>/AGENTS.md` → this packaged copy (via `appdir/monitor/MONITOR.md`). `AGENTS.md` is the emerging cross-tool agent-instructions convention; monitor reads it so repos that already maintain one for other tools (Codex CLI, etc.) work without a separate file. Monitor-specific names beat the cross-tool name within the chain. The `build/` fallback lets a build pipeline generate a project-specific copy without touching the repo root. The path is read once at startup and frozen for the session — `:cd` later does not re-resolve.

## Working principle

Match the project's existing idioms — don't impose your own. Before changing anything in an unfamiliar codebase, identify the language, framework, layout, and test posture, then operate consistent with what's there. If you're unsure how the project does X, grep for an existing example before writing new code.

## Orientation order

When entering an unfamiliar codebase, look at these until you have enough signal to act:
1. `README.md`, `CONTRIBUTING.md` — stated structure and conventions, if present.
2. The manifest/build file (`pyproject.toml`, `Package.swift`, `*.xcodeproj`/`*.xcworkspace`, `package.json`, `Cargo.toml`, `go.mod`, etc.) — the most reliable source of truth for dependencies, entry points, and tooling.
3. Top-level directory listing — distinguishes app vs library vs CLI layouts at a glance.
4. The test directory — what's tested signals what's considered observable behavior.
5. Lockfiles (`Package.resolved`, `uv.lock`, `package-lock.json`, etc.) — confirm exact dependency versions if version-sensitive.

## Swift / iOS

**Project shape:**
- `*.xcodeproj` or `*.xcworkspace` → Xcode-managed (most iOS apps). Files are organized into groups inside the project; the on-disk layout often mirrors the group structure but not always — verify by reading the directory directly.
- `Package.swift` → Swift Package Manager library or CLI. Sources live in `Sources/<Target>/`, tests in `Tests/<TargetTests>/`.
- Both present → an app consuming local SPM modules, or an SPM package with an example app.

**Common iOS app layout:**
- Entry: `<App>App.swift` (SwiftUI, marked `@main`) or `AppDelegate.swift` + `SceneDelegate.swift` (UIKit).
- Groupings like `Models/`, `Views/`, `ViewModels/`, `Services/` are typical but not universal — many apps stay flat.
- `Assets.xcassets`, `Info.plist`, and `*.xcconfig` are part of the project surface, not just static data.

**Tests:** XCTest classes inheriting from `XCTestCase`; files typically named `<TypeName>Tests.swift`. UI tests live in a separate target under `<App>UITests/`. Run via Xcode's test runner, `xcodebuild test`, or `swift test` for SPM.

## Python

**Project shape:**
- `pyproject.toml` (modern, preferred) → inspect `[project]`, `[project.scripts]` (CLI entry points), and `[tool.*]` (configured linters/formatters/type-checkers).
- `setup.py` or `setup.cfg` only → older project; a `pyproject.toml` may still exist alongside.
- No manifest → a script collection. Look for `requirements.txt` or just direct imports.

**Layouts:**
- `src/<pkg>/` layout → package source under `src/`, tests under `tests/` (often mirroring the package).
- Flat layout → `<pkg>/` at root, tests under `tests/` or as `test_*.py` siblings.
- Single-file scripts → standalone `.py` files at root.

**Entry points:**
- `if __name__ == "__main__":` block in a module.
- `[project.scripts]` in `pyproject.toml` (the value points to `module:function` — that function is the CLI's `main`).
- `python -m <pkg>` if `<pkg>/__main__.py` exists.

**Tests:** pytest is dominant (functions `test_*`, classes `Test*`). Run with `pytest` or `python -m pytest`. unittest still appears in older codebases.

## Other languages

If the project is none of the above (Node, Go, Rust, Java, etc.), the same principle applies: identify the build/manifest file (`package.json`, `go.mod`, `Cargo.toml`, `pom.xml`/`build.gradle`, etc.), let it tell you about dependencies, entry points, and tooling, then grep for existing patterns before writing new code.

## Monitor wiki guidance

Treat the monitor-wiki as a compact, curated project knowledge layer rather than a second copy of the repository.

- Use the monitor-wiki for stable project knowledge such as architecture, conventions, subsystem boundaries, recurring workflows, and durable pitfalls.
- Keep monitor-wiki content compact, high-signal, and organized around repository overviews, subsystems, workflows, conventions, and gotchas.
- Do not let the monitor-wiki become a source-tree mirror, a page-per-file inventory, or a large generated catalog of symbols.
- Prefer the monitor-wiki for durable project guidance, but prefer source code and newer project-local documentation when they materially disagree with wiki content.
- Consult project wiki content before planning or editing when substantive wiki content already exists and the task is architectural, cross-cutting, convention-sensitive, or explicitly asks for project guidance.
- Start with `INDEX.md` and load only the additional wiki pages that are clearly relevant to the task.
- Suggest wiki updates when code changes affect stable project knowledge, but do not automatically rewrite wiki content unless the user requests it or the workflow explicitly allows it.

## Monitor wiki linter guidance

Treat the monitor-wiki linter as a separate, optional maintenance workflow rather than part of the default code-writing path.

- Do not run the wiki-linter automatically on every startup.
- Do not run the wiki-linter automatically on every code change.
- Prefer cheap deterministic structural checks before considering any semantic or LLM-assisted linting.
- Use semantic drift checks only when explicitly requested or when a material wiki/code discrepancy suggests a lint pass is warranted.
- Prefer source code and newer project-local documentation over stale wiki content when they disagree.
- Report focused, actionable findings and recommend targeted wiki updates rather than broad rewrites.
- Do not automatically rewrite wiki content unless the user requests it or the workflow explicitly allows it.

## Surfacing project facts

When you discover facts about a project that aren't in this file (custom build flags, non-obvious test runners, project-specific naming conventions, known broken areas), surface them so the user can decide whether to land them in a project-local `MONITOR.md`.
