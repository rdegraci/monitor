# PLAN_MONITOR_OOP

## Goal
Rewrite Monitor as a new, isolated Python application in an object-oriented style with free-function orchestration, while keeping the legacy app intact as the baseline reference. The current codebase already includes the classic CLI REPL as the default interactive mode, and the prompt_toolkit-based TUI is available via `--tui` with file-only logging during startup and runtime while the REPL logs to both screen and file.

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
- Each runtime instance must own its own config, history, macros, status, logger, prompt, and session state.
- No new code path in `src/monitor_oop/` should mutate `src/monitor/` state.
- Logging is configured once at centralized bootstrap, and runtime code uses standard module loggers.
- Log files follow a per-process convention under the user config directory `log/` subdirectory as `monitor_<pid>.log`.
- The current prompt_toolkit-based TUI uses file-only logging during startup and while active, and the default CLI REPL logs to both screen and file.
- The TUI status line color mapping is idle green and working yellow.
- The current TUI implementation uses a transcript pipeline split into a transcript buffer, renderer, and viewport rather than a single private helper-only path, and the remaining interaction and verification polish is still in progress.

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
  - Resolves `system_prompt` from `appdirs.user_config_dir("monitor")/system_prompt`, seeding it from `system_prompt.example` on first run and exposing the resolved prompt text to bootstrap and request construction.
  - Coordinates with `PromptStore` so prompt resolution follows the current path-resolution approach without leaking prompt-file state into runtime code.
- `PromptService`
  - Owns prompt loading, default seeding, and prompt text access for the runtime instance.
  - Provides the system prompt as an explicit dependency to the LLM request flow.
  - Keeps prompt state private behind the service boundary.
  - Relies on `ConfigService` and `PromptStore` for system-prompt path resolution and persistence.
- `PromptStore`
  - Persists the system prompt text and related prompt files under the user config directory.
  - Encapsulates prompt file resolution, first-run seeding, and read/write operations behind a narrow API.
  - Works with `ConfigService` to resolve `system_prompt` from the user config directory and maintain the current prompt-file layout.
- `HistoryService`
  - Owns a `History` domain object for conversation state.
  - Manages history persistence, deterministic compaction replacement, and flushing through `History`.
  - `ConversationSession` triggers deterministic compaction, `HistoryService` performs replacement and turn tracking, and `SummarizationService` now generates the summary text as part of that boundary.
  - Compaction is owned by the conversation/history layer, with `SummarizationService` generating summary text as part of that boundary.
  - The current minimal config surface for compaction and summarization is `CONVERSATION_MAX_TURNS`, `summarization.maximum_summary_tokens`, and `summarization.prompt_template`.
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
  - Supports quiet TUI bootstrap so the prompt_toolkit-based interface can use file-only logging while active.
  - Writes per-process logs under the user config directory `log/` subdirectory using `monitor_<pid>.log`.
  - Supports the default CLI REPL with both screen and file logging.
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
- `ToolCallHandler`
  - Handles tool-call parsing, normalization, output wrapping, and orchestration.
  - Delegates tool state and execution to `ToolRegistry` / `ToolService`.
- `LLMService`
  - Acts as a façade over the collaborators that build requests, parse responses, and coordinate transport for the current runtime.
  - Delegates tool handling to `ToolCallHandler`.
  - Enforces finish-reason handling for `stop`, `length`, `tool_calls`, `content_filter`, and `None`.
  - Applies a defensive maximum tool loop cap of 16 total model calls.
- `LLMRequestBuilder`
  - Extracts and shapes LLM request payloads from session, history, macro, tool, prompt, and context inputs.
  - Keeps request construction isolated from execution, transport, and response handling concerns.
  - Injects the system prompt as the first system message in the request payload.

Suggested ownership flow:
- `MonitorApp` creates `RuntimeContext`.
- `RuntimeContext` creates or receives service instances.
- `ConversationSession` depends on `ConfigService`, `HistoryService`, `MacroService`, `CommandProcessor`, and prompt access provided through the runtime.
- `CommandProcessor` delegates to services rather than reaching into global state.
- `ServerApp` uses the same `RuntimeContext` as CLI and script modes.
- `LoggerService` is initialized during centralized bootstrap and shared through explicit context wiring, while runtime modules continue to use standard `logging.getLogger(__name__)` access.
- The prompt_toolkit-based TUI uses file-only logging during startup and while active, and runtime logging stays quiet in the terminal while the TUI is active.
- `PromptService` and `PromptStore` provide a future-friendly seam for prompt specialization and subagent-oriented prompt variants without committing to subagent behavior yet.
- Prompt-related tests and import paths have been added alongside the new prompt subsystem so prompt loading, seeding, and request injection are exercised through the new package layout.

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
- The new app must construct its own config, history, macros, status, logger, prompt, and session state per process or per app instance.
- Any legacy behavior that is reused must be wrapped behind new interfaces.
- Shared helpers must be stateless or pure unless explicitly isolated behind a service boundary.
- Startup code in `src/monitor_oop/` must not depend on side effects from `src/monitor/`.
- The legacy app remains the reference implementation until the new app is verified.
- The TUI path uses file-only logging during construction and while active, and runtime logging remains quiet in the terminal while the TUI is active.
- The TUI status line color mapping is idle green and working yellow.

## Suggested Package Layout
- `src/monitor_oop/`
  - `__init__.py`
  - `core/app.py`
  - `core/runtime_context.py`
  - `core/config_service.py`
  - `core/prompt_service.py`
  - `core/prompt_store.py`
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
  - `core/tools/tool_call_handler.py`
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
- Keep the first slice narrow: config load, prompt loading, session creation, logging bootstrap, and a basic command dispatch path.
- Seed `system_prompt` from `appdirs.user_config_dir("monitor")/system_prompt` using `system_prompt.example` on first run, and wire the resolved prompt into bootstrap so it can be passed through the LLM request path as the initial system message.
- Add the `PromptService` / `PromptStore` seam early so prompt loading remains isolated and ready for future prompt specialization or subagent-oriented extensions without committing to those behaviors yet.
- Add prompt-focused tests and import-path coverage early so the new prompt subsystem is exercised through `src/monitor_oop/` rather than legacy modules.
- Ensure the prompt_toolkit-based TUI can be brought up with file-only logging during app construction, with runtime logs kept out of the terminal while the interactive session is active.
- The TUI status line color mapping is idle green and working yellow.
- The current TUI transcript pipeline uses the transcript buffer, renderer, and viewport split, and there is still verification and interaction polish remaining around that flow.

### Milestone 2: Core runtime ownership
- Implement isolated config, history, macro, logger, prompt, and status services.
- Move conversation lifecycle management into `ConversationSession`.
- Implement command classification and execution through `CommandProcessor`.
- Ensure runtime state is owned by `RuntimeContext` and passed explicitly.
- Track multi-call tool handling, envelope bookkeeping, batched follow-up payload support, and turn-scoped lifecycle management via `ToolTurnState` as first-class runtime behaviors within the new tool workflow, keeping orchestration free-function driven and service state isolated.
- Validate the tool workflow against the current test adjustments so the latest tool-calling path, loop handling, turn-state lifecycle, and follow-up payload assembly remain covered under repeated runs.
- Keep prompt-resolution tests aligned with the current `ConfigService` and `PromptStore` path resolution so `system_prompt` loading and injection remain verified end to end.
- Next refactor target: strict bootstrap ownership, with runtime constructors no longer creating fallback dependencies.
- Checklist:
  - build_app creates services
  - RuntimeContext stores references
  - services do not create other services
  - prompt/config/LLM boundaries stay stable and explicit

### Milestone 3: Server mode
- Add an isolated HTTP server implementation in `ServerApp`.
- Ensure all request handling uses only `RuntimeContext` and new app services.
- Verify server startup does not read or mutate legacy app state.

### Milestone 4: Verification
- Add regression tests comparing new behavior to legacy behavior.
- Validate startup, chat flow, command flow, logging, prompt loading, and server flow.
- Confirm there is no shared mutable state between `src/monitor/` and `src/monitor_oop/`.
- Confirm the test suite mirrors the source tree, including `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/`, so runtime modules and tool modules are exercised in parallel with the new package layout.
- Confirm multi-call tool execution, envelope bookkeeping, turn-scoped tool lifecycle handling, and batched follow-up payload support are preserved within the isolated runtime design.
- Keep verification notes aligned with the latest tool-calling implementation so the plan tracks both runtime behavior and the corresponding test updates.
- Verify `system_prompt` loading, first-run seeding, and injection as the first system message in LLM request construction.
- Verify prompt-related import paths and tests continue to resolve through the new prompt subsystem layout.
- Apply the following rules-of-thumb during implementation and review:
  - `build_app` creates services and other runtime dependencies.
  - `RuntimeContext` stores references to the constructed services and per-run state.
  - Services do not create other services; they consume injected dependencies instead.
  - Prompt, config, and LLM boundaries remain stable and explicit across bootstrap, request construction, and runtime execution.
- Bootstrap ownership should be explicit and strict, with runtime constructors avoiding fallback dependency creation.
- The prompt_toolkit-based TUI is covered by verification for file-only logging during construction and suppressed terminal logging while active.
- Verify the transcript buffer, renderer, and viewport split, along with the remaining TUI interaction and polish work, before treating the TUI flow as complete.

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
- Prompt-loading drift if `system_prompt` bootstrap, request injection, and user-config persistence are not kept as a first-class path.
- Prompt subsystem drift if `ConfigService`, `PromptStore`, prompt-specific tests, and package import paths diverge from the current resolution approach.
- Noisy runtime logging while the prompt_toolkit-based TUI is active if file-only logging behavior is not preserved.
- TUI interaction drift if the transcript buffer, renderer, and viewport split is not covered by the remaining verification work.

## Success Criteria
- The new app runs independently from the legacy app.
- The new app does not mutate legacy globals.
- The new app can be started, tested, and extended in isolation.
- The new app preserves current user-facing behavior where intended.
- The legacy app remains available under `src/monitor/` throughout the migration.
- Multi-call tool handling, envelope bookkeeping, turn-scoped tool lifecycle management, and batched follow-up payload support are preserved within the isolated runtime design.
- The latest tool-calling implementation is reflected in the verification plan and in the test adjustments that exercise it.
- `system_prompt` is loaded from the user config directory, seeded on first run, and injected as the first system message in the LLM request flow.
- Prompt loading, seeding, and import paths are covered by the new prompt subsystem tests.
- The prompt_toolkit-based TUI continues to use file-only logging during construction and while active, and the default REPL logs to both screen and file.
- The TUI status line color mapping is idle green and working yellow.
- The TUI transcript buffer, renderer, and viewport split is documented and verified, with the remaining interaction polish work tracked to completion.

## Starter Blueprint
- Recommended package layout:
  - `src/monitor_oop/__init__.py`
  - `src/monitor_oop/core/app.py`
  - `src/monitor_oop/core/runtime_context.py`
  - `src/monitor_oop/core/config_service.py`
  - `src/monitor_oop/core/prompt_store.py`
  - `src/monitor_oop/core/prompt_service.py`
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
  - `MonitorApp` owns startup, mode selection, and lifecycle coordination.
  - `RuntimeContext` owns process-local services and per-run state and acts as the explicit wiring point for CLI, server, and script modes.
  - `ConfigService`, `HistoryService`, `MacroService`, `StatusService`, `LoggerService`, and `PromptService` own their own state and do not create each other.
  - `HistoryService` owns a `History` domain object, and `History` encapsulates messages privately behind its API instead of exposing direct storage.
  - `ConversationSession` triggers deterministic compaction, `HistoryService` performs replacement and turn tracking, and `SummarizationService` now generates the summary text.
  - `PromptService` owns the resolved system prompt and uses `PromptStore` to persist and seed the prompt file under the user config directory.
  - `PromptStore` resolves the prompt path under `appdirs.user_config_dir("monitor")/system_prompt`, seeds from `system_prompt.example` on first run, and exposes the current prompt text without leaking prompt-file state.
  - `ConversationSession` owns chat-session flow and depends on services through explicit injection.
  - `ConversationSession` uses `prompt_toolkit` `PromptSession` configured with `FileHistory` backed by the prompt history path for up-arrow prompt recall.
  - `ConversationSession` exposes `is_running` as the read-only lifecycle indicator for the active session.
  - `CommandProcessor` classifies and dispatches commands through service calls.
  - `ServerApp` reuses the same `RuntimeContext` as CLI and script modes.
  - `LoggerService` configures logging once at centralized bootstrap, and runtime modules use standard module loggers.
  - `PromptService` and `PromptStore` are explicit runtime dependencies so prompt loading, seeding, and request construction stay isolated from the rest of the bootstrap graph.
  - The prompt_toolkit-based TUI uses file-only logging during app construction and suppresses terminal logs while active.
  - The TUI status line color mapping is idle green and working yellow.
  - The current TUI transcript pipeline is split across a transcript buffer, renderer, and viewport, with some verification and interaction polish still outstanding.
  - `ToolRegistry` / `ToolService` owns tool registration, resolution, and execution state behind a private internal store.
  - Tool-specific dataclasses live in `src/monitor_oop/core/tools/tool_models.py`.
  - The tool package exists under `src/monitor_oop/core/tools/`, with `tool_models.py`, `registry.py`, `tool_service.py`, `parsing.py`, `tool_call_handler.py`, and per-tool modules such as `weather.py`.
  - Tool definitions, adapters, and invocation metadata remain private to the tool service boundary.
  - Tool-call parsing, normalization, output wrapping, and orchestration are handled by free functions as needed, with service calls used for actual tool state and execution.
  - The weather tool is registered at startup through the app bootstrap.
  - `LLMService` enforces finish-reason handling for `stop`, `length`, `tool_calls`, `content_filter`, and `None`.
  - `LLMService` applies a defensive maximum tool loop cap of 16 total model calls.
  - Multi-call tool handling, envelope bookkeeping, batched follow-up payload support, and turn-scoped tool lifecycle management through `ToolTurnState` are part of the expected tool workflow behavior in the new app.
  - The latest tool-calling test coverage should verify normalization, repeated tool loops, turn-state lifecycle, envelope assembly, and follow-up payload dispatch without depending on legacy state.
  - `system_prompt` is loaded from the user config directory, seeded from `system_prompt.example` on first run, and supplied to LLM request construction as the initial system message.
  - Prompt subsystem tests and import paths should target `src/monitor_oop/core/prompt_service.py` and `src/monitor_oop/core/prompt_store.py` directly to keep coverage aligned with the resolved layout.
  - The prompt_toolkit-based TUI uses file-only logging during app construction and suppresses terminal logs while active.
- Startup order:
  - Parse entrypoint args in `main()`.
  - Build `MonitorApp`.
  - Construct `RuntimeContext`.
  - Initialize config first, then prompt, logger, history, macros, and status.
  - Create `ConversationSession`.
  - Enter CLI, server, or script workflow.
- Thin-slice first implementation:
  - Start with config loading, prompt loading, a minimal runtime context, session creation, logging bootstrap, and one command dispatch path.
  - Keep orchestration in free functions and keep services small.
  - Make the first runnable path CLI only, with `--tui` as the alternate interactive mode using file-only logging.
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
  - `core/prompt_store.py`
  - `core/prompt_service.py`
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
