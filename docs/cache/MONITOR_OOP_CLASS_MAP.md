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

## RuntimeContext
`src/monitor_oop/core/runtime_context.py`

Owns the isolated runtime services and per-run state for the staged implementation.

### Constructor
- `config_service: ConfigService`
- `history_service: HistoryService`
- `macro_service: MacroService`
- `status_service: StatusService`
- `logger_service: LoggerService`
- `command_processor: CommandProcessor`
- `tool_registry: ToolRegistry`
- `tool_service: ToolService`
- `llm_service: LLMService`
- `server_app: ServerApp | None = None`

### Public Methods
- `create_session() -> ConversationSession`

### Responsibilities
- Provide a single dependency graph for the app instance.
- Keep state local to the new app process.
- Own the staged service wiring without reaching into module globals.
- Supply shared services to sessions, server handlers, and workflows.
- Track the current implementation structure alongside the mirrored test layout under `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/`.
- Refer to `ARCHITECTURE_OOP.md` for the high-level architecture overview of this design.

## ConfigService
`src/monitor_oop/core/config_service.py`

Handles isolated configuration loading and access.

### Constructor
- `initial_config: RuntimeConfig | None = None`

### Public Methods
- `load() -> None`
- `reset(force: bool = False) -> None`
- `select_model(model_name: str) -> bool`
- `get_model() -> str`
- `get_context_window() -> int`

### Responsibilities
- Load and validate app configuration.
- Resolve `OPENAI_API_KEY` from the environment, the project `.env`, the appdirs user config `.env`, and `~/.config/monitor/.env`.
- Manage model selection and config reset behavior.

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
Owns conversation history and persistence.

### Constructor
- `config_service: ConfigService`

### Public Methods
- `initialize() -> None`
- `append(message: Message) -> None`
- `flush() -> None`
- `trim(count: int) -> None`
- `summarize_if_needed() -> bool`
- `reset_with_summary(summary_text: str) -> None`

### Responsibilities
- Own a `History` instance.
- Manage in-memory conversation state plus persistence and summarization behavior.
- Persist and summarize history.
- Keep token-related behavior isolated.
- Support the current temporary mixed storage flow where needed by the thin slice implementation.

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
- Load macros.
- Expand macro expressions.
- Keep macro definitions private.
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

## LLMService
Owns LLM request/response orchestration and completion handling.

### Constructor
- `config_service: ConfigService`
- `tool_service: ToolService`
- `history_service: HistoryService`
- `status_service: StatusService`

### Public Methods
- `complete(messages: list[Message]) -> str`
- `respond(messages: list[Message]) -> str`
- `run_with_tools(messages: list[Message]) -> str`

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
Owns provider-specific LLM response invocation and low-level completion transport.

### Constructor
- `config_service: ConfigService`

### Public Methods
- `complete(request: object) -> object`
- `stream(request: object) -> object`

### Responsibilities
- Invoke the configured model provider.
- Keep provider transport isolated from response orchestration.
- Serve as the low-level client used by `LLMService`.

## ConversationSession
`src/monitor_oop/core/conversation_session.py`

Owns one interactive chat session.

### Constructor
- `context: RuntimeContext`

### Public Methods
- `start() -> int`
- `step() -> bool`
- `prompt_user() -> str`
- `handle_model_switch() -> None`
- `process_user_input(user_input: str) -> bool`

### Responsibilities
- Own the REPL/session lifecycle.
- Manage prompt state and session-scoped chat behavior.
- Coordinate with services through the runtime context.
- Expose the session `is_running` read-only property for lifecycle state.
- Handle the current placeholder non-LLM response flow used by the thin slice implementation.

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
- `main() -> int`
- `run_cli(app: MonitorApp) -> int`
- `run_server(app: MonitorApp) -> int`
- `run_script(app: MonitorApp, script_path: str) -> int`
- `reset_config(app: MonitorApp, force: bool = False) -> None`
- `process_user_input(session: ConversationSession, text: str) -> bool`

Parsing, normalization, and output wrapping can remain free functions in this layer as needed.

The workflow layer currently provides the interactive CLI loop.

## Shared Data Models
Define these in `models.py`:
- `AppMode`
- `RuntimeConfig`
- `Message`
- `CommandType`
- `CommandResult`
- `AppState`
- `ToolDefinition`
- `ToolResult`

## Dependency Rules
- `MonitorApp` owns `RuntimeContext`.
- `RuntimeContext` owns service instances.
- `ConversationSession` and `ServerApp` use `RuntimeContext` only.
- `CommandProcessor` depends on services, not on module globals.
- `ToolService` depends on `ToolRegistry`, not on module globals.
- No class in `monitor_oop` should read state from `monitor` at runtime.
- The test suite mirrors `src/monitor_oop/core/` under `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/` so implementation and coverage stay aligned.
