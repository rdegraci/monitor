# PLAN_MONITOR_OOP

## Goal
Rewrite Monitor as a new, isolated Python application in an object-oriented style with free-function orchestration, while keeping the legacy app intact as the baseline reference.

## Package Boundaries
- Legacy application code stays under `src/monitor/`.
- New isolated application code lives under `src/monitor_oop/`.
- The two packages must not share mutable module globals.
- The new package may reuse legacy logic only through explicit, stateless, or safely wrapped interfaces.
- Any shared code must be reviewed for statefulness before reuse.

## Principles
- Keep `src/monitor/` unchanged and usable as the current production reference.
- Build the new app in parallel inside `src/monitor_oop/`.
- Prefer explicit dependency injection over implicit module state.
- Use classes to own state and subsystem behavior.
- Use free functions for orchestration and workflow composition.
- Each runtime instance must own its own config, history, macros, status, and session state.
- No new code path in `src/monitor_oop/` should mutate `src/monitor/` state.

## Runtime Object Graph
The new app should build a clear runtime graph at startup:

- `MonitorApp`
  - Top-level coordinator for startup, mode selection, and lifecycle management.
- `RuntimeContext`
  - Owns references to all services and per-run state.
- `ConfigService`
  - Loads, validates, and exposes app configuration, including `OPENAI_API_KEY` from the process environment, the project `.env`, the appdirs user config path, and the fallback `~/.config/monitor/.env`.
- `HistoryService`
  - Manages conversation state, persistence, summarization, and flushing.
- `MacroService`
  - Manages macro loading, expansion, and editing workflows.
- `StatusService`
  - Owns runtime status state and optional status server integration.
- `ConversationSession`
  - Owns a single interactive chat session and its state.
- `CommandProcessor`
  - Classifies commands and executes command-specific behavior.
- `ServerApp`
  - Builds and runs the HTTP API for the new app.

Suggested ownership flow:
- `MonitorApp` creates `RuntimeContext`.
- `RuntimeContext` creates or receives service instances.
- `ConversationSession` depends on `ConfigService`, `HistoryService`, `MacroService`, and `CommandProcessor`.
- `CommandProcessor` delegates to services rather than reaching into global state.
- `ServerApp` uses the same `RuntimeContext` as CLI and script modes.

## Free Functions
Keep orchestration outside the classes where practical:
- `main()`
- `run_cli(app)`
- `run_server(app)`
- `run_script(app, script_path)`
- `reset_config(app, force=False)`
- `process_user_input(session, text)`
- `evaluate_command(command)`
- `execute_command(result, command, context)`

These functions should coordinate the runtime object graph, not own long-lived state.

## Separation Rules
- The new app must not import legacy module globals for runtime state.
- The new app must not mutate legacy caches, singleton objects, or module-level configuration.
- The new app must construct its own config, history, macros, status, and session state per process or per app instance.
- Any legacy behavior that is reused must be wrapped behind new interfaces.
- Shared helpers must be stateless or pure unless explicitly isolated behind a service boundary.
- Startup code in `src/monitor_oop/` must not depend on side effects from `src/monitor/`.
- The legacy app remains the reference implementation until the new app is verified.

## Suggested Package Layout
- `src/monitor_oop/`
  - `__init__.py`
  - `core/app.py`
  - `core/runtime_context.py`
  - `core/config_service.py`
  - `core/conversation_session.py`
  - `core/command_processor.py`
  - `core/history_service.py`
  - `core/macro_service.py`
  - `core/status_service.py`
  - `core/server_app.py`
  - `core/workflow.py`
  - `models.py`
  - `utils.py`

## Implementation-Ready Milestone Plan
### Milestone 1: Thin-slice bootstrap
- Create the `src/monitor_oop/` package and module scaffolding.
- Define the runtime object graph and constructor dependencies.
- Add a minimal `main()` entrypoint that can instantiate `MonitorApp`.
- Wire one end-to-end startup path for CLI mode using the new runtime only.
- Keep the first slice narrow: config load, session creation, and a basic command dispatch path.

### Milestone 2: Core runtime ownership
- Implement isolated config, history, macro, and status services.
- Move conversation lifecycle management into `ConversationSession`.
- Implement command classification and execution through `CommandProcessor`.
- Ensure runtime state is owned by `RuntimeContext` and passed explicitly.

### Milestone 3: Server mode
- Add an isolated HTTP server implementation in `ServerApp`.
- Ensure all request handling uses only `RuntimeContext` and new app services.
- Verify server startup does not read or mutate legacy app state.

### Milestone 4: Verification
- Add regression tests comparing new behavior to legacy behavior.
- Validate startup, chat flow, command flow, and server flow.
- Confirm there is no shared mutable state between `src/monitor/` and `src/monitor_oop/`.

### Milestone 5: Cutover decision
- Decide whether to keep both apps or promote the new app to primary.
- Change defaults only after the new app is stable and behavior is verified.

## Key Risks
- Duplicated logic during migration.
- Divergence in behavior between legacy and new app.
- Accidental reuse of mutable globals.
- A monolithic `MonitorApp` that absorbs responsibilities better handled by services.
- Hidden coupling through imports, caches, or module-level initialization.

## Success Criteria
- The new app runs independently from the legacy app.
- The new app does not mutate legacy globals.
- The new app can be started, tested, and extended in isolation.
- The new app preserves current user-facing behavior where intended.
- The legacy app remains available under `src/monitor/` throughout the migration.

## Starter Blueprint
- Recommended package layout:
  - `src/monitor_oop/__init__.py`
  - `src/monitor_oop/core/app.py`
  - `src/monitor_oop/core/runtime_context.py`
  - `src/monitor_oop/core/config_service.py`
  - `src/monitor_oop/core/history_service.py`
  - `src/monitor_oop/core/macro_service.py`
  - `src/monitor_oop/core/status_service.py`
  - `src/monitor_oop/core/command_processor.py`
  - `src/monitor_oop/core/conversation_session.py`
  - `src/monitor_oop/core/server_app.py`
  - `src/monitor_oop/core/workflow.py`
  - `src/monitor_oop/models.py`
  - `src/monitor_oop/utils.py`
- Runtime object graph:
  - `MonitorApp` owns startup and mode selection.
  - `RuntimeContext` owns process-local services and per-run state.
  - `ConfigService`, `HistoryService`, `MacroService`, and `StatusService` own their own state.
  - `ConversationSession` owns chat-session flow and depends on services through explicit injection.
  - `CommandProcessor` classifies and dispatches commands through service calls.
  - `ServerApp` reuses the same `RuntimeContext` as CLI and script modes.
- Startup order:
  - Parse entrypoint args in `main()`.
  - Build `MonitorApp`.
  - Construct `RuntimeContext`.
  - Initialize config first, then history, macros, and status.
  - Create `ConversationSession`.
  - Enter CLI, server, or script workflow.
- Thin-slice first implementation:
  - Start with config loading, a minimal runtime context, session creation, and one command dispatch path.
  - Keep orchestration in free functions and keep services small.
  - Make the first runnable path CLI only.
- Avoid early:
  - Sharing module-level mutable state with `src/monitor/`.
  - Building server mode before CLI startup is verified.
  - Adding cross-service shortcuts that bypass `RuntimeContext`.
  - Folding all behavior into `MonitorApp`.
  - Reusing legacy globals, caches, or singleton initialization.
- Recommended first file order:
  - `models.py`
  - `core/runtime_context.py`
  - `core/config_service.py`
  - `core/history_service.py`
  - `core/macro_service.py`
  - `core/status_service.py`
  - `core/command_processor.py`
  - `core/conversation_session.py`
  - `core/workflow.py`
  - `core/app.py`
  - `core/server_app.py`
  - `utils.py`
  - `__init__.py`
- The first-pass class map and build sequence are defined in `MONITOR_OOP_CLASS_MAP.md` and `MONITOR_OOP_IMPLEMENTATION_SEQUENCE.md` to keep the implementation aligned with this blueprint.

## Tracking Documents
- `PLAN_MONITOR_OOP`
- `MONITOR_OOP_CLASS_MAP.md`
- `MONITOR_OOP_IMPLEMENTATION_SEQUENCE.md`
- `MONITOR_OOP_VERIFICATION_PLAN.md` as the verification reference
