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
- See `docs/cache/PLAN_RATE_LIMITING.md` for the upcoming provider-aware LLM send-path rate limiting design; the future Anthropic LiteLLM adapter should share the same limiter, and the future rate-limiting loader should resolve model aliases through explicit provider-table tier references.

## Runtime Object Graph
The new app should build a clear runtime graph at startup; see `ARCHITECTURE_OOP.md` for the overview:

- `MonitorApp`
  - Top-level coordinator for startup, mode selection, and lifecycle management.
- `RuntimeContext`
  - Owns references to all services and per-run state.
  - Carries the resolved model fields produced during bootstrap so request construction and policy checks use the same applied configuration.
  - Serves as the explicit wiring point for CLI, script, and server modes.
  - The first implementation slice also includes `RequestCapacityService` and `RateLimitService` as explicit runtime services used by `LLMResponseClient` for preflight orchestration.
- `ConfigService`
  - Loads, validates, and exposes app configuration, including `OPENAI_API_KEY` from the process environment, the project `.env`, the appdirs user config path, and the fallback `~/.config/monitor/.env`.
  - Startup sequence: seed or copy `config.yaml.example` if needed, seed or copy the packaged `model_config_v2.json` into the user config directory if needed, load `.env` with the existing precedence, then load `system_prompt` from its seeded file.
  - Planned config flow: package `config.yaml.example` in `src/monitor_oop`, preserve `appdirs.user_config_dir("monitor")/config.yaml` if it already exists, otherwise copy `config.yaml.example` there on first run, load `config.yaml` from the user config directory with fallback to `~/.config/monitor/`, and load `.env` using `find_dotenv(usecwd=True)` before falling back to the user config directory and `~/.config/monitor/`.
  - Resolves configurable persistent prompt history settings via `history_dir` and `prompt_history_filename`, with the default path `<user_config_dir>/history/prompt_history`, rather than introducing a separate `FileHistoryService`.
  - Resolves `system_prompt` from `appdirs.user_config_dir("monitor")/system_prompt`, seeding it from `system_prompt.example` on first run and exposing the resolved prompt text to bootstrap and request construction.
  - Coordinates with `PromptStore` so prompt resolution follows the current path-resolution approach without leaking prompt-file state into runtime code.
  - Resolves model configuration from the packaged `src/monitor_oop/model_config_v2.json` source as the greenfield model config for the new app, copying it into the user config directory on first run if it is missing, mirroring the `config.yaml.example` seed behavior, with the schema definition documented in `docs/cache/PLAN_MODEL_CONFIG_V2.md`.
  - Applies the resolved model configuration during bootstrap and exposes the resolved model fields through `RuntimeContext` for downstream request construction, fit checks, and rate-limit preflight.
  - Context/output window values are used for fit checks and completion headroom during request construction, while the actual rate-limiting policy remains separate; context-window pressure can also trigger compaction before rate-limit preflight, while rate limiting itself remains a separate policy service.
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
  - Resolves model aliases through explicit provider-table tier references when the future rate-limiting loader is introduced.
  - Context/output window values are used for fit checks and completion headroom during request construction, while the actual rate-limiting policy remains separate; context-window pressure can also trigger compaction before rate-limit preflight, while rate limiting itself remains a separate policy service.

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
