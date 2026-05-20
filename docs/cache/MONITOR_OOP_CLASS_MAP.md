# monitor_oop Class Map

This document defines the first-pass object model for the isolated Monitor rewrite.
For the high-level architecture overview of the current `monitor_oop` design, see `ARCHITECTURE_OOP.md`.

## MonitorApp
`src/monitor_oop/core/app.py`

Top-level coordinator for startup, mode selection, and lifecycle management.

### Constructor
- `context: RuntimeContext`

### Public Methods
- `run() -> int`
- `run_cli() -> int`
- `run_server() -> int`
- `run_script(script_path: str) -> int`
- `reset_config(force: bool = False) -> None`

### Responsibilities
- Own the runtime context.
- Select the workflow based on startup arguments.
- Coordinate shutdown and process exit.

## TuiApp
`src/monitor_oop/core/presentation/tui.py`

Prompt_toolkit-backed presentation controller for the interactive UI.

### Constructor (dataclass fields)
- `runtime_context: RuntimeContext`
- `turn_coordinator: TurnCoordinator`
- `layout: TuiLayout = field(default_factory=build_layout)`
- `event_queue: Deque[object] = field(default_factory=deque)`
- `is_running: bool = False`
- `status_text: str = "idle"`
- `input_draft: str = ""`
- `active_task_id: str = ""`

### Public Methods
- `start() -> None`
- `run() -> None`
- `stop() -> None`
- `enqueue_event(event: object) -> None`
- `enqueue_input_draft_event(draft_text: str) -> None`
- `drain_events() -> None`
- `drain_pending_completions() -> None`
- `sync_active_task_id() -> None`

### Responsibilities
- Own the prompt_toolkit `Application` with a three-pane layout (output / status / input).
- Coordinate the output widget, status control, and input widget via a transcript buffer + renderer + viewport split.
- Run turns off the UI thread via a `ThreadPoolExecutor`; UI thread is the only mutator of `TuiApp` state.
- Register itself as `runtime_context.status_listener` so mid-turn phase transitions (`compacting`, `working`) reach the status line immediately via direct mutation + `application.invalidate()`.
- Maintain the status state machine: `idle` (green) → `working` / `compacting` / `rate limited (idle)` (yellow) → `completed (idle)` (green) / `failed (idle)` (red).
- Catch `RateLimitDeniedError` from worker threads and tag the resulting `TurnCompletionResult` with `failure_kind="rate_limited"` for distinct rendering.
- Manage the TUI lifecycle and user interaction loop.

## RuntimeContext
`src/monitor_oop/core/runtime_context.py`

Owns the isolated runtime services and per-run state.

### Constructor
- `config_service: ConfigService`
- `history_service: HistoryService`
- `llm_service: LLMService`
- `macro_service: MacroService`
- `status_service: StatusService`
- `prompt_service: PromptService`
- `summarization_service: SummarizationService`
- `command_processor: CommandProcessor`
- `tool_service: ToolService`
- `tool_registry: ToolRegistry`
- `request_capacity_service: RequestCapacityService`
- `rate_limit_service: RateLimitService`
- `compaction_store` (`CompactionStore | None`)
- `server_app=None`
- `logger_service: LoggerService | None = None`

### Public Methods
- `create_session() -> ConversationSession`
- `set_status_listener(listener: Callable[[str], None] | None) -> None`
- `emit_status(text: str) -> None`
- `status_listener` (read-only property)
- Plus read-only accessors over each privately stored service.

### Responsibilities
- Provide a single dependency graph for the app instance.
- Keep state local to the new app process.
- Own service wiring without reaching into module globals.
- Supply shared services to sessions, server handlers, and workflows.
- Carry an optional presentation-layer status listener used by `ConversationSession` to emit mid-turn phase transitions (`compacting`, `working`). CLI/server paths leave the listener unset.
- Refer to `ARCHITECTURE_OOP.md` for the high-level architecture overview.

## ConfigService
`src/monitor_oop/core/config_service.py`

Acts as a façade over `ConfigLoader` and `EnvLoader` for isolated configuration loading and access.

### Constructor
- `initial_config: RuntimeConfig | None = None`

### Public Methods
- `load() -> None`
- `reset(force: bool = False) -> None`
- `select_model(full_model_name: str) -> bool`
- `get_model() -> str`
- `get_context_window() -> int`

### Responsibilities
- Load and validate app configuration through the loader collaborators.
- Apply `model_config_v2.json` during bootstrap.
- Resolve `OPENAI_API_KEY` from the environment, the project `.env`, the appdirs-first user config `.env`, and the explicit `~/.config/monitor/.env` fallback.
- Manage model selection and config reset behavior.
- Coordinate history path resolution through the appdirs-first user config dir, with explicit fallback to `~/.config/monitor` when needed.
- Provide the configured history compaction template and history limits to the runtime services that use them.
- Keep deterministic compaction inputs isolated from higher-level session flow.
- Expose `api_model_name` as the adapter-facing model accessor.
- Preserve `get_model()` as compatibility behavior for callers that still expect the legacy model-name lookup.

## PromptStore
Owns file-backed persistence for the resolved system prompt.

### Constructor
- `config_service: ConfigService`

### Public Methods
- `load() -> str`
- `save(prompt_text: str) -> None`
- `reload() -> str`
- `seed_from_example() -> None`

### Responsibilities
- Depend on `ConfigService` for user config path resolution.
- Persist the system prompt under `appdirs.user_config_dir("monitor")/system_prompt`.
- Seed prompt storage from `system_prompt.example` when no stored prompt exists.
- Keep prompt file handling isolated from higher-level services.
- Provide the file-backed backing store used by `PromptService`.

## PromptService
Owns the resolved system prompt for the runtime.

### Constructor
- `config_service: ConfigService`
- `prompt_store: PromptStore`

### Public Methods
- `load() -> None`
- `get() -> str`
- `reload() -> None`

### Responsibilities
- Own the runtime system prompt.
- Resolve and hold the active system prompt for the runtime.
- Load prompt content from `PromptStore` during bootstrap.
- Reload the prompt when file-backed content changes.
- Keep the runtime system prompt isolated from LLM request construction.
- Provide the resolved system prompt to request-building collaborators.

## History
Owns the ordered conversation messages.

### Constructor
- `_messages: list[Message]`

### Public Methods
- `append(message: Message) -> None`
- `trim(count: int) -> None`
- `clear() -> None`
- `snapshot() -> list[Message]`

### Responsibilities
- Hold the ordered conversation messages.
- Be owned by `HistoryService`.
- Keep the conversation message collection isolated from other app state.

## HistoryService
Owns conversation history, compaction decision, and compaction replacement.

### Constructor
- `config_service`
- `compaction_store=None` (`CompactionStore | None` — best-effort persistence)

### Public Methods
- `append(message: Message) -> None`
- `append_message(message: Message) -> None`
- `clear() -> None`
- `trim(count: int) -> None`
- `snapshot() -> list[Message]`
- `messages` (compatibility property, returns snapshot)
- `should_compact(context_window=None, estimated_token_count=None, output_window=None) -> bool`
- `compact(summary_text: str) -> None`
- `reset_with_summary(summary_text: str) -> None`

### Responsibilities
- Own a `History` instance and the boundary tracker that preserves complete units across compaction.
- Decide when compaction should run via `should_compact`, evaluating in order: (1) soft context-window trigger (`estimated_token_count >= context_window * compaction_soft_ratio`), (2) hard context-window trigger (input + reserved output ≥ window), (3) turn-budget cliff.
- Perform the compaction replacement on `compact()`: clear, append the system summary, append the preserved tail (size = `summarization_settings.preserve_units`), sync trackers, persist summary best-effort.
- Persist compaction summaries through the injected `CompactionStore` (forensic-only — never read back).
- Keep token-related behavior delegated to the canonical `ConfigService.estimate_token_usage` estimator via the call site in `ConversationSession`.

## SummarizationService
LLM-backed summary generator with a deterministic fallback for compaction.

### Constructor
- `config_service`
- `request_builder: LLMRequestBuilder`
- `response_client: LLMResponseClient`
- `response_adapter: ResponsesOpenAiAdapter`
- `summarization_prompt_template: str | None = None`

### Public Methods
- `summarize(messages: Sequence[Message]) -> str`

### Responsibilities
- Generate summaries from older conversation history using the LLM-backed flow.
- Resolve the token limit via `ConfigService.get_summarization_token_limit()` and clamp to `output_window` before passing as `max_output_tokens` to the response client (so the cap is enforced on the wire, not a soft prompt hint).
- Build summary requests through `LLMRequestBuilder.build_summarization_input` and dispatch through `LLMResponseClient.create_response(..., max_output_tokens=...)`.
- On LLM failure or empty response, return a deterministic fallback that carries forward the prior system summary (capped at `token_limit × 4` chars, truncating from the end so the original LLM-derived prefix survives accumulated placeholder lines) plus a new `[Compacted summary placeholder for N prior messages]` line. Monotonic across repeated failures, bounded against unbounded growth.
- Produce summary text suitable for reinsertion into compacted conversation state via `HistoryService.compact`.
- Keep summary generation isolated from the rest of the session flow.

## CompactionStore
`src/monitor_oop/core/compaction_store.py`

Forensic-only persistence boundary for compacted summaries. Nothing in the running application reads these files back; they exist for human inspection / offline tooling.

### Constructor (dataclass)
- `base_dir: Path`

### Public Methods
- `save(summary_text: str, pid: int | None = None, timestamp: str | None = None) -> Path`
- `persist_summary(summary_text: str, pid: int | None = None, timestamp: str | None = None) -> Path`

### Responsibilities
- Write each compaction summary to `compact-<pid>-YYYY-MM-DD-HH-MM-SS.summary` using exclusive-create open mode (race-safe across concurrent writers).
- On filename collision, append `-N` to the stem (`-1`, `-2`, ...) until a free name is found.
- After every successful save, opportunistically delete any `compact-*.summary` files older than 30 days from the base directory (best-effort; per-file `OSError` is logged and ignored).
- Tolerate `None`/empty `base_dir` at the wiring layer — `app.py` checks `get_compaction_dir_path()` returned a usable path and passes `compaction_store=None` to `HistoryService` if not, with a warning log.

## MacroService
Owns macro state and expansion workflows.

### Constructor
- `config_service: ConfigService`

### Public Methods
- `load() -> None`
- `expand(text: str) -> str`
- `add_definition(raw_text: str) -> bool`
- `list_macros() -> dict[str, str]`
- `reload() -> None`

### Responsibilities
- Act as a façade over `MacroStore` and `MacroExpander`.
- Load macro definitions from `MacroStore` during bootstrap.
- Delegate macro expansion to `MacroExpander`.
- Persist `add_definition` changes back through `MacroStore`.
- Keep macro definitions private within the service boundary for the thin slice implementation.
- Support simple runtime macro updates without recursive expansion logic in the service layer.
- Preserve current behavior while future parity work introduces dedicated `MacroStore` and `MacroExpander` collaborators.
- Load macros.
- Expand macro expressions.
- Handle runtime macro updates.

## StatusService
Owns app status state and optional status server integration.

### Constructor
- `initial_state: str = "idle"`

### Public Methods
- `set_idle() -> None`
- `set_working() -> None`
- `get_state() -> str`
- `start_server() -> str`
- `stop_server() -> None`

### Responsibilities
- Track runtime working/idle status.
- Manage the optional status server if enabled.

## LoggerService
Owns logging configuration and runtime log routing.

### Constructor
- `config_service: ConfigService`

### Public Methods
- `configure() -> None`
- `get_logger(name: str) -> object`
- `reset() -> None`

### Responsibilities
- Provide the centralized logging configuration point.
- Configure application logging for the isolated runtime.
- Keep logger setup and routing isolated from module globals.
- Serve as the single owner of logging initialization for the app instance.
- Work with the staged runtime configuration rather than module-level logging state.

## CommandProcessor
Classifies and executes commands.

### Constructor
- `config_service: ConfigService`
- `history_service: HistoryService`
- `macro_service: MacroService`
- `status_service: StatusService`

### Public Methods
- `evaluate(command: str) -> CommandResult`
- `execute(result: CommandResult, original_command: str) -> CommandResult`
- `process(command: str) -> CommandResult`

### Responsibilities
- Determine what a command is.
- Dispatch command execution.
- Return structured results instead of loose booleans.

## ToolRegistry
Owns registered tool definitions and lookup metadata.

### Constructor
- `_tools: dict[str, ToolDefinition]`

### Public Methods
- `register(tool: ToolDefinition) -> bool`
- `unregister(tool_name: str) -> bool`
- `list_tools() -> dict[str, ToolDefinition]`
- `resolve(tool_name: str) -> ToolDefinition | None`
- `has_tool(tool_name: str) -> bool`

### Responsibilities
- Keep private storage for registered tools.
- Provide lookup and listing for available tools.
- Support isolated tool registration without module globals.
- Serve as the single source of truth for tool metadata.

## ToolService
Owns tool execution workflows and tool invocation behavior.

### Constructor
- `tool_registry: ToolRegistry`

### Public Methods
- `execute(tool_name: str, arguments: dict[str, object]) -> ToolResult`
- `register_tool(tool: ToolDefinition) -> bool`
- `list_tools() -> dict[str, ToolDefinition]`
- `resolve_tool(tool_name: str) -> ToolDefinition | None`
- `prepare_batch_calls(calls: list[dict[str, object]]) -> list[dict[str, object]]`
- `record_envelope(envelope: dict[str, object]) -> None`
- `apply_batched_follow_up(payloads: list[dict[str, object]]) -> None`

### Responsibilities
- Depend on the registry for tool lookup and storage.
- Execute registered tools through a controlled service boundary.
- Expose registration and listing operations to higher layers.
- Keep tool execution logic isolated from command and session state.
- Mediate tool lookup/execution for the staged model flow.
- Support multiple tool calls in a single assistant turn.
- Maintain envelope-based bookkeeping for tool-call groups.
- Coordinate batched follow-up payloads for downstream processing.
- Preserve the association between a model turn, its tool envelope, and the resulting tool outputs.

## ToolCallHandler
Owns model-requested tool call handling and execution coordination.

### Constructor
- `tool_service: ToolService`
- `status_service: StatusService`

### Public Methods
- `handle_tool_calls(calls: list[dict[str, object]]) -> list[dict[str, object]]`
- `handle_follow_up(payloads: list[dict[str, object]]) -> None`

### Responsibilities
- Coordinate tool execution requested by the model.
- Delegate tool lookup and execution to `ToolService`.
- Manage batched tool-call handling within a single assistant turn.
- Preserve the relationship between model tool requests and tool outputs.
- Support follow-up payload processing after tool execution.
- Keep tool-call orchestration isolated from `LLMService`.

## RequestCapacityService
Owns request sizing and capacity decisions for LLM traffic.

### Constructor
- `config_service: ConfigService`

### Public Methods
- `get_capacity() -> int`
- `set_capacity(capacity: int) -> None`
- `reset() -> None`

### Responsibilities
- Track request capacity derived from runtime configuration.
- Provide request sizing limits used by LLM response handling.
- Keep capacity policy isolated from response orchestration.

## RateLimitService
Pure admission-control gate for provider-facing LLM calls. Wait/queue semantics belong in a separate scheduler layer if needed (not implemented).

### Constructor
- `config_service: ConfigService`
- `window_seconds: int = 60`
- `response_chain_cache_size: int = 256`

### Public Methods
- `check_request(model: str, estimated_tokens: int) -> None` — returns on success, raises `RateLimitDeniedError` on denial.
- `estimate_token_usage(model, messages, tools, previous_response_id) -> int` — chain-aware: cached `previous_response_id` adds the prior response's `total_tokens` as a baseline.
- `record_request_for_model(model: str, tokens: int) -> None` — records actual or estimated usage after dispatch.
- `record_response_total_tokens(response_id: str | None, total_tokens: int | None) -> None` — populates the LRU cache used by `estimate_token_usage`.

### Responsibilities
- Maintain a model-keyed rolling-window of token + request-count events (default window 60s); evict expired events on every access; thread-safe via `RLock`.
- Normalize accounting keys (strip `provider/` prefix, lowercase) so `"openai/gpt-4o"` and `"gpt-4o"` share a budget.
- Resolve TPM/RPM limits via `ConfigService.get_model_tpm_limit / get_model_rpm_limit`. Missing TPM → unlimited + WARNING log. Missing RPM → ERROR log + `sys.exit(1)` (mandatory config). Explicit `0` is coerced to `None` at the accessor (same as missing).
- On denial, raise `RateLimitDeniedError` with structured fields (`reason="tpm"|"rpm"`, `model`, `current`, `limit`, `retry_after_seconds` computed from the oldest in-window event timestamp).
- Maintain a bounded LRU of `response_id → total_tokens` keyed by `response.id` so future requests chained via `previous_response_id` can account for server-side context.

## RateLimitDeniedError
Typed exception raised by `RateLimitService.check_request` on denial.

### Fields
- `reason: str` (`"tpm"` or `"rpm"`)
- `model: str`
- `current: int`
- `limit: int`
- `retry_after_seconds: float | None`

### Behavior
- `str(exc)` renders a human-readable message including current/limit and approximate retry window.
- Caught and surfaced by the REPL (`workflow._run_cli_session`) as `[rate limit] <message>` to stdout; the loop continues.
- Caught and surfaced by `TuiApp._execute_turn`, which tags the `TurnCompletionResult` with `failure_kind="rate_limited"` so the status line shows a yellow `"rate limited (idle)"` indicator + red transcript line, distinct from generic red `"failed (idle)"`.

## LLMRequestBuilder
Owns request shaping for LLM completions.

### Constructor
- `prompt_text: str | None = None`

### Public Methods
- `build_input(history: list[str | Message], prompt_text: str | None = None) -> list[dict[str, Any]]`
- `build_summarization_input(prompt_text: str, message_history: list[Message]) -> list[dict[str, str]]`
- `strip_provider_prefix(model: str) -> str`

### Responsibilities
- Shape provider requests by rendering them from history alone — the caller must ensure the latest user turn is the final entry in history. The previous contract (a separate `user_input` argument appended on top) silently duplicated the user message in every request and has been removed.
- Emit tool-call metadata (`tool_calls`, `tool_call_id`, `name`) on each request message when present on the `Message` so the boundary tracker's preservation of tool-call clusters survives end-to-end through the request layer.
- Optionally inject a system prompt as the first message in the request.
- Keep request construction isolated from provider transport and completion handling.
- The summarization input builder no longer interpolates `{messages}` into the prompt template (which previously could double the history when a custom template used the placeholder); only `{message_count}` is interpolated. The hard output cap is enforced by the response client via `max_output_tokens`, not by a soft string hint in the prompt.

## LLMService
Owns LLM request/response orchestration and completion handling.

### Constructor
- `config_service`
- `request_builder: LLMRequestBuilder`
- `response_client: LLMResponseClient`
- `tool_call_handler: ToolCallHandler`
- `adapter: ResponsesOpenAiAdapter`
- `tool_service: ToolService`
- `prompt_service: PromptService`

### Public Methods
- `complete(history: list[str | Message]) -> TurnCompletionResult`

### Responsibilities
- Drive the staged model interaction flow for completions.
- Handle response items, finish-reason branching, and tool-call continuation.
- Orchestrate tool calls when the model requests them.
- Enforce a defensive maximum of 16 tool-call loops before aborting.
- Convert partial model output into a completed response.
- Keep LLM response flow isolated from command processing and session state.
- Support batched tool-call handling within a single turn.
- Consume tool envelopes and produce follow-up payloads through the tool service.
- Delegate tool execution coordination to `ToolCallHandler`.
- Delegate request shaping to `LLMRequestBuilder`.
- Delegate provider invocation to `LLMResponseClient`.
- Move toward a façade role over extracted collaborators as request construction, continuation handling, and completion orchestration are separated.

## LLMResponseClient
Owns provider-specific LLM response invocation, preflight gating, and post-call usage recording.

### Constructor
- `config_service: ConfigService`
- `adapter: ResponsesOpenAiAdapter`
- `tool_service: ToolService | None = None`
- `request_capacity_service: RequestCapacityService | None = None`
- `rate_limit_service: RateLimitService | None = None`

### Public Methods
- `create_response(input_messages, previous_response_id=None, max_output_tokens=None) -> Any`

### Responsibilities
- Run the request-capacity preflight first (`request_capacity_service.request_fits`); raise `ValueError` on rejection.
- Run the rate-limit preflight (`rate_limit_service.check_request`); the typed `RateLimitDeniedError` propagates to the REPL/TUI.
- Invoke the configured model provider via `adapter.complete(..., max_output_tokens=...)`. The `max_output_tokens` parameter is plumbed end-to-end so summarization caps are real, not soft string hints.
- After successful dispatch, record usage. Prefers the provider-reported `response.usage.total_tokens` (or `input_tokens + output_tokens` / `prompt_tokens + completion_tokens` shape variants) over the preflight estimate so the rolling budget tracks actual usage.
- Cache `response.id → total_tokens` on the rate-limit service so future requests chained via `previous_response_id` get a chain-aware estimate baseline.
- Keep provider transport isolated from response orchestration.

## ConversationSession
`src/monitor_oop/core/conversation_session.py`

Owns one interactive chat session.

### Constructor
- `context: RuntimeContext`

### Public Methods
- `start() -> int`
- `step() -> bool`
- `read_user_input() -> str`
- `handle_model_switch() -> None`
- `process_user_input(user_input: str) -> str | None`
- `submit_input(user_input: str) -> ConversationTurnResult | None`

### Responsibilities
- Own the REPL/session lifecycle.
- Manage prompt state and session-scoped chat behavior.
- Coordinate with services through the runtime context.
- Expose the session `is_running` read-only property for lifecycle state.
- Append the user message to history, then run compaction *proactively* (before the LLM call). On compaction, emit `"compacting"` via `context.emit_status`, run summarization + replacement, then restore `"working"` in a `try/finally`.
- Estimate compaction token usage by converting `Message` dataclasses to request-shaped dicts (`{"role", "content"}`) before calling `config_service.estimate_token_usage` — earlier the dataclasses were passed directly and the estimator silently failed inside a broad except, leaving the context-window compaction trigger permanently disabled.
- Hand the generated summary text to `HistoryService.compact(...)` for the replacement step.
- Convert submitted input into a `ConversationTurnResult` for downstream UI and workflow handling.

## ServerApp
`src/monitor_oop/core/server_app.py`

Creates and runs the isolated HTTP API.

### Constructor
- `context: RuntimeContext`

### Public Methods
- `create_app() -> Flask`
- `run(host: str, port: int) -> None`
- `convert_messages_to_command(messages: list[dict]) -> str`

### Responsibilities
- Build the Flask app.
- Register routes.
- Call into the new runtime context only.
- Serve as a placeholder for the future HTTP implementation in the thin slice.

## Workflow Functions
`src/monitor_oop/core/workflow.py`

These remain free functions because they orchestrate object behavior:
- `run_cli(app: MonitorApp) -> int`
- `run_server(app: MonitorApp) -> int`
- `run_script(app: MonitorApp, script_path: str) -> int`
- `reset_config(app: MonitorApp, force: bool = False) -> None`
- `process_user_input(session: ConversationSession, text: str) -> bool`

The CLI loop catches `RateLimitDeniedError` raised from `session.process_user_input` and prints `[rate limit] <message>` to stdout, then `continue`s — the REPL stays alive so the user can wait and retry.

Parsing, normalization, and output wrapping can remain free functions in this layer as needed.

## Shared Data Models
Define these in `models.py`:
- `AppMode`
- `RuntimeConfig`
- `SummarizationSettings`
- `Message`
- `ToolCall`
- `History`
- `CommandType`
- `CommandResult`
- `AppState`
- `ResolvedRuntimeConfig`

`RuntimeConfig` carries model config fields, including `full_model_name`, the adapter-facing `api_model_name`, and the model limits used during bootstrap and runtime. `api_model_name` is the adapter-facing accessor.

`SummarizationSettings` carries:
- `token_limit: int = 4000` — output cap for the summarization LLM call (enforced via `max_output_tokens`).
- `prompt_template: str` — the summarization prompt template (only `{message_count}` is interpolated).
- `preserve_units: int = 2` — number of conversational units to preserve from the tail during compaction.
- `compaction_soft_ratio: float = 0.5` — proactive context-window trigger as a fraction of the window. Setting outside `(0, 1)` disables the soft trigger; hard backstop still applies.

The canonical name is `summarization_settings` on `RuntimeConfig`. Legacy property aliases (`summarization`, `compaction_config`) have been removed.

`Message` carries `role`, `content`, optional `name`, optional `tool_call_id`, optional `tool_calls`, optional `response_id`, optional `parent_response_id`. These fields are emitted by `LLMRequestBuilder` when present, so tool-call clusters preserved by the boundary tracker survive end-to-end through the request layer.

`ConversationTurnResult` (in `core/conversation_session.py`) and `TurnCompletionResult` (in `core/presentation/turn_results.py`) are distinct: the former is the session-level outcome; the latter is the worker-to-UI handoff including a `failure_kind` field (`"rate_limited"` is the only recognized non-default value, surfacing a distinct transient indicator in the TUI).

## Dependency Rules
- `MonitorApp` owns `RuntimeContext`.
- `RuntimeContext` owns service instances.
- `ConversationSession` and `ServerApp` use `RuntimeContext` only.
- `CommandProcessor` depends on services, not on module globals.
- `ToolService` depends on `ToolRegistry`, not on module globals.
- `LLMResponseClient` uses `RequestCapacityService` and `RateLimitService` from the runtime graph.
- No class in `monitor_oop` should read state from `monitor` at runtime.
- The test suite mirrors `src/monitor_oop/core/` under `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/` so implementation and coverage stay aligned.
