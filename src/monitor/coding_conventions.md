# INSTRUCTIONS

## Purpose
Treat this document as the authoritative operating manual. When you reason about the repository, summarize it, choose files, or make changes, obey these rules exactly so the result stays deterministic, traceable, and easy for tools to verify. This source is packaged as `instructions.md`, and the copy under `appdir/` is the runtime-monitored instructions file that the app reads at execution time.

## Goals
- Infer the repository structure consistently.
- Trace references and dependencies with minimal ambiguity.
- Predict impact areas before changing code.
- Select the most relevant tests with high precision.
- Keep prompt and instruction handling predictable.

## Repository layout conventions

### Layer mapping
Use directory names as the primary signal for layer ownership and enforce this mapping:
- `presentation/` for UI and rendering
- `application/` for orchestration and request assembly
- `core/` for services, coordination, and business workflow
- `infrastructure/` for file I/O, config, persistence, adapters, and external integrations
- `tests/` for test coverage

When you infer architecture, treat path-based layer mapping as the first and strongest signal. Use it to determine which code owns the behavior and which files are relevant.

### File naming conventions
Use file names to identify responsibility quickly and deterministically:
- `*_service.py` for service objects
- `*_builder.py` for request or data assembly
- `*_store.py` for persistence or disk-backed state
- `*_client.py` for external system adapters
- `*_handler.py` for event or tool execution handlers
- `*_controller.py` or `*_coordinator.py` for workflow coordination

When you choose files to inspect or modify, prefer the files whose names match the behavior you need to change.

### Entry point conventions
Treat these as likely entry points and bootstrap surfaces:
- `app.py`
- `main.py`
- `__main__.py`
- bootstrap or wiring modules

Start with these when you need to understand startup flow, initialization, or cross-cutting wiring.

## Dependency conventions
- Make higher-level orchestration depend on lower-level services.
- Keep infrastructure from owning business policy.
- Use application code to assemble requests and coordinate flows.
- Keep presentation code free of deep business logic.
- Mirror test files to the area they validate when practical.

When you trace dependencies, follow the ownership direction implied by the layer: start from orchestration or entry points, then follow collaborators downward.

## Tooling-friendly conventions

### Summary rules
When summarizing the repository:
- group files by layer first
- rank bootstrap and orchestration files above helpers
- use deterministic ordering
- keep descriptions compact and high-signal
- exclude docs and cache files unless they are directly relevant

Produce summaries that let a deterministic tool identify the architecture, central files, and likely change surfaces quickly.

### Reference tracing rules
When tracing references:
- start from the most central service or entry point
- include callers, collaborators, and tests
- prefer exact symbol names over free-text matches when possible
- keep the trace compact and ordered

Use symbol-level precision whenever it is available. Prefer traces that show the smallest complete path from entry point to implementation to test.

### Impact analysis rules
When estimating impact:
- prioritize shared services, request builders, adapters, and bootstrap code
- include tests near the touched module
- treat layer boundaries as likely fault lines
- note whether the change is local or cross-cutting

Decide impact from ownership and dependency direction, not from textual similarity alone.

### Test selection rules
When selecting tests:
- prefer tests adjacent to the changed module
- include service tests before broad integration tests
- include request-builder or adapter tests for request flow changes
- include presentation tests for UI behavior changes
- include smoke tests only when startup or wiring changes are involved

Choose the smallest test set that covers the changed behavior and its nearest integration points.

## Prompt and instruction conventions
- Keep the base system prompt short and stable.
- Keep repo-specific working instructions separate when possible.
- Load companion instructions only when they are relevant to the task.
- Prefer deterministic task-routing rules over ad hoc prompt growth.

Use these conventions to avoid instruction sprawl and to keep task handling predictable.

## Change conventions
- Prefer the smallest robust change.
- Reuse existing abstractions before creating new ones.
- Choose the layer that owns the behavior.
- Avoid workaround-style fixes when the root cause is clearly elsewhere.
- Add or update tests near the affected behavior.

When you modify code, make durable changes that match the repository's architecture instead of patching symptoms.

## Summary for deterministic tools
If a tool needs to infer architecture, rely on this order:
1. path-based layer mapping
2. file naming patterns
3. bootstrap and coordinator roles
4. test proximity
5. dependency direction

Use this order consistently when you summarize the repo, pick files, or estimate impact. These conventions must remain stable so tool output remains predictable and useful.
