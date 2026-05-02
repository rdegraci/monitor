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
- Each runtime instance must own its own config, history, macros, status, logger, and session state.
- No new code path in `src/monitor_oop/` should mutate `src/monitor/` state.
- Logging is configured once at centralized bootstrap, and runtime code uses standard module loggers.

## Runtime Object Graph
The new app should build a clear runtime graph at startup; see `ARCHITECTURE_OOP.md` for the overview:

- `MonitorApp`
  - Top-level coordinator for startup, mode selection, and lifecycle management.
- `RuntimeContext`
  - Owns references to all services and per-run state.
  - Serves as the explicit wiring point for CLI, script, and server modes.
- `ConfigService`
  - Loads, validates, and exposes app configuration, including `OPENAI_API_KEY` from the process environment, the project `.env`, the appdirs user config path, and the fallback `~/.config/monitor/.env`.
  - Planned config flow: package `config.yaml.example` in `src/monitor_oop`, preserve `appdirs.user_config_dir("monitor")/config.yaml` if it already exists, otherwise copy `config.yaml.example` there on first run, load `config.yaml` from the user config directory with fallback to `~/.config/monitor/`, and load `.env` using `find_dotenv(usecwd=True)` before falling back to the user config directory and `~/.config/monitor/`.
  - Resolves configurable persistent prompt history settings via `history_dir` and `prompt_history_filename`, with the default path `<user_config_dir>/history/prompt_history`, rather than introducing a separate `FileHistoryService`.
- `HistoryService`
  - Owns a `History` domain object for conversation state.
  - Manages history persistence, summarization, and flushing through `History`.
- `History`
  - Encapsulates conversation messages behind a private internal store.
  - Stores messages privately and exposes a controlled API for history access and mutation.
- `MacroService`
  - Manages macro loading, expansion, and editing workflows.
  - Keeps macro definitions private behind the service boundary.
- `StatusService`
  - Owns runtime status state and optional status server integration.
- `LoggerService`
  - Owns logging bootstrap state and logger configuration for the runtime instance.
  - Configures logging once at centralized startup and exposes module logger access patterns through standard Python logging.
- `ConversationSession`
  - Owns a single interactive chat session and its state.
  - Uses `prompt_toolkit` `PromptSession` configured with `FileHistory` backed by the prompt history path for up-arrow prompt recall.
  - Exposes `is_running` as a read-only view of session lifecycle state instead of a public running attribute.
- `CommandProcessor`
  - Classifies commands and executes command-specific behavior.
- `ServerApp`
  - Builds and runs the HTTP API for the new app.
- `ToolRegistry` / `ToolService`
  - Owns tool definitions, registration, and invocation state behind a private internal store.
  - Exposes a controlled API for listing, resolving, validating, and dispatching tools without leaking mutable tool state.
  - Keeps tool-call metadata, adapters, and execution context isolated behind the service boundary.
  - Turn-scoped tool state is handled by the dedicated `ToolTurnState` helper, keeping per-turn lifecycle data isolated from the registry and service stores.
- `LLMService`
  - Acts as a façade over extracted collaborators for LLM request construction, response handling, and transport coordination.
  - Enforces finish-reason handling for `stop`, `length`, `tool_calls`, `content_filter`, and `None`.
  - Applies a defensive maximum tool loop cap of 16 total model calls.
- `LLMRequestBuilder`
  - Extracts and shapes LLM request payloads from session, history, macro, tool, and context inputs.
  - Keeps request construction isolated from execution, transport, and response handling concerns.

Suggested ownership flow:
- `MonitorApp` creates `RuntimeContext`.
- `RuntimeContext` creates or receives service instances.
- `ConversationSession` depends on `ConfigService`, `HistoryService`, `MacroService`, and `CommandProcessor`.
- `CommandProcessor` delegates to services rather than reaching into global state.
- `ServerApp` uses the same `RuntimeContext` as CLI and script modes.
- `LoggerService` is initialized during centralized bootstrap and shared through explicit context wiring, while runtime modules continue to use standard `logging.getLogger(__name__)` access.

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

For tool calling workflows, free functions should also handle OpenAI Responses API response parsing, tool call normalization, output wrapping, and orchestration as needed, while delegating tool registry and execution state to `ToolRegistry` / `ToolService`. The weather tool is registered at startup through the app bootstrap. The current plan state reflects completed multi-call tool handling, envelope bookkeeping, batched follow-up payload support, and turn-scoped lifecycle handling through `ToolTurnState`, so follow-up orchestration should preserve those behaviors while keeping state isolated behind the service boundary.

## Separation Rules
- The new app must not import legacy module globals for runtime state.
- The new app must not mutate legacy caches, singleton objects, or module-level configuration.
- The new app must construct its own config, history, macros, status, logger, and session state per process or per app instance.
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
  - `core/logger_service.py`
  - `core/server_app.py`
  - `core/workflow.py`
  - `core/application/llm_request_builder.py`
  - `core/infrastructure/llm_response_client.py`
  - `models.py`
  - `utils.py`
- `tests/monitor_oop/`
  - `core/`
  - `core/tools/`

## Implementation-Ready Milestone Plan
### Milestone 1: Thin-slice bootstrap
- Create the `src/monitor_oop/` package and module scaffolding.
- Define the runtime object graph and constructor dependencies.
- Add a minimal `main()` entrypoint that can instantiate `MonitorApp`.
- Wire one end-to-end startup path for CLI mode using the new runtime only.
- Keep the first slice narrow: config load, session creation, logging bootstrap, and a basic command dispatch path.

### Milestone 2: Core runtime ownership
- Implement isolated config, history, macro, logger, and status services.
- Move conversation lifecycle management into `ConversationSession`.
- Implement command classification and execution through `CommandProcessor`.
- Ensure runtime state is owned by `RuntimeContext` and passed explicitly.
- Track multi-call tool handling, envelope bookkeeping, batched follow-up payload support, and turn-scoped lifecycle management via `ToolTurnState` as first-class runtime behaviors within the new tool workflow, keeping orchestration free-function driven and service state isolated.
- Validate the tool workflow against the current test adjustments so the latest tool-calling path, loop handling, turn-state lifecycle, and follow-up payload assembly remain covered under repeated runs.

### Milestone 3: Server mode
- Add an isolated HTTP server implementation in `ServerApp`.
- Ensure all request handling uses only `RuntimeContext` and new app services.
- Verify server startup does not read or mutate legacy app state.

### Milestone 4: Verification
- Add regression tests comparing new behavior to legacy behavior.
- Validate startup, chat flow, command flow, logging, and server flow.
- Confirm there is no shared mutable state between `src/monitor/` and `src/monitor_oop/`.
- Confirm the test suite mirrors the source tree, including `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/`, so runtime modules and tool modules are exercised in parallel with the new package layout.
- Confirm multi-call tool execution, envelope tracking, batched follow-up payload handling, turn-scoped tool lifecycle handling, and the associated test coverage remain stable under repeated tool loops and mixed command flows.
- Keep verification notes aligned with the latest tool-calling implementation so the plan tracks both runtime behavior and the corresponding test updates.

### Milestone 5: Cutover decision
- Decide whether to keep both apps or promote the new app to primary.
- Change defaults only after the new app is stable and behavior is verified.

## Key Risks
- Duplicated logic during migration.
- Divergence in behavior between legacy and new app.
- Accidental reuse of mutable globals.
- A monolithic `MonitorApp` that absorbs responsibilities better handled by services.
- Hidden coupling through imports, caches, or module-level initialization.
- Regression in multi-call tool orchestration, envelope bookkeeping, turn-scoped tool lifecycle state, or batched follow-up payload assembly if workflow boundaries are not kept explicit.
- Tool-path test drift if the implementation and the latest assertions are not updated together.

## Success Criteria
- The new app runs independently from the legacy app.
- The new app does not mutate legacy globals.
- The new app can be started, tested, and extended in isolation.
- The new app preserves current user-facing behavior where intended.
- The legacy app remains available under `src/monitor/` throughout the migration.
- Multi-call tool handling, envelope bookkeeping, turn-scoped tool lifecycle management, and batched follow-up payload support are preserved within the isolated runtime design.
- The latest tool-calling implementation is reflected in the verification plan and in the test adjustments that exercise it.

## Starter Blueprint
- Recommended package layout:
  - `src/monitor_oop/__init__.py`
  - `src/monitor_oop/core/app.py`
  - `src/monitor_oop/core/runtime_context.py`
  - `src/monitor_oop/core/config_service.py`
  - `src/monitor_oop/core/history_service.py`
  - `src/monitor_oop/core/macro_service.py`
  - `src/monitor_oop/core/status_service.py`
  - `src/monitor_oop/core/logger_service.py`
  - `src/monitor_oop/core/command_processor.py`
  - `src/monitor_oop/core/conversation_session.py`
  - `src/monitor_oop/core/workflow.py`
  - `src/monitor_oop/core/server_app.py`
  - `src/monitor_oop/models.py`
  - `src/monitor_oop/utils.py`
- Runtime object graph:
  - `MonitorApp` owns startup and mode selection.
  - `RuntimeContext` owns process-local services and per-run state.
  - `ConfigService`, `HistoryService`, `MacroService`, `StatusService`, and `LoggerService` own their own state.
  - `HistoryService` owns a `History` domain object, and history state is stored in `History` rather than a raw list.
  - `History` encapsulates messages privately behind its API, instead of exposing direct message storage.
  - `ConversationSession` owns chat-session flow and depends on services through explicit injection.
  - `ConversationSession` uses `prompt_toolkit` `PromptSession` configured with `FileHistory` backed by the prompt history path for up-arrow prompt recall.
  - `ConversationSession` exposes `is_running` as the read-only lifecycle indicator for the active session.
  - `CommandProcessor` classifies and dispatches commands through service calls.
  - `ServerApp` reuses the same `RuntimeContext` as CLI and script modes.
  - `LoggerService` configures logging once at centralized bootstrap, and runtime modules use standard module loggers.
  - `ToolRegistry` / `ToolService` owns tool registration, resolution, and execution state behind a private internal store.
  - Tool-specific dataclasses live in `src/monitor_oop/core/tools/tool_models.py`.
  - The tool package exists under `src/monitor_oop/core/tools/`, with `tool_models.py`, `registry.py`, `tool_service.py`, `parsing.py`, and per-tool modules such as `weather.py`.
  - Tool definitions, adapters, and invocation metadata remain private to the tool service boundary.
  - Tool-call parsing, normalization, output wrapping, and orchestration are handled by free functions as needed, with service calls used for actual tool state and execution.
  - The weather tool is registered at startup through the app bootstrap.
  - `LLMService` enforces finish-reason handling for `stop`, `length`, `tool_calls`, `content_filter`, and `None`.
  - `LLMService` applies a defensive maximum tool loop cap of 16 total model calls.
  - Multi-call tool handling, envelope bookkeeping, batched follow-up payload support, and turn-scoped tool lifecycle management through `ToolTurnState` are part of the expected tool workflow behavior in the new app.
  - The latest tool-calling test coverage should verify normalization, repeated tool loops, turn-state lifecycle, envelope assembly, and follow-up payload dispatch without depending on legacy state.
- Startup order:
  - Parse entrypoint args in `main()`.
  - Build `MonitorApp`.
  - Construct `RuntimeContext`.
  - Initialize config first, then logger, history, macros, and status.
  - Create `ConversationSession`.
  - Enter CLI, server, or script workflow.
- Thin-slice first implementation:
  - Start with config loading, a minimal runtime context, session creation, logging bootstrap, and one command dispatch path.
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
  - `core/logger_service.py`
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
- `ARCHITECTURE_OOP.md`
- `MONITOR_OOP_CLASS_MAP.md`
- `MONITOR_OOP_IMPLEMENTATION_SEQUENCE.md`
- `MONITOR_OOP_VERIFICATION_PLAN.md` as the verification reference
