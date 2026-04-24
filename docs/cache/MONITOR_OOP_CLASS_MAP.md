# monitor_oop Class Map

This document defines the first-pass object model for the isolated Monitor rewrite.

## MonitorApp
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
Owns the isolated runtime services and per-run state.

### Constructor
- `config_service: ConfigService`
- `history_service: HistoryService`
- `macro_service: MacroService`
- `status_service: StatusService`
- `command_processor: CommandProcessor`
- `server_app: ServerApp | None = None`

### Public Methods
- `create_session() -> ConversationSession`

### Responsibilities
- Provide a single dependency graph for the app instance.
- Keep state local to the new app process.

## ConfigService
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
- Manage model selection and config reset behavior.

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
- Manage conversation state.
- Persist and summarize history.
- Keep token-related behavior isolated.

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

## ConversationSession
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

## ServerApp
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

## Workflow Functions
These remain free functions because they orchestrate object behavior:
- `main() -> int`
- `run_cli(app: MonitorApp) -> int`
- `run_server(app: MonitorApp) -> int`
- `run_script(app: MonitorApp, script_path: str) -> int`
- `reset_config(app: MonitorApp, force: bool = False) -> None`
- `process_user_input(session: ConversationSession, text: str) -> bool`

## Shared Data Models
Define these in `models.py`:
- `AppMode`
- `RuntimeConfig`
- `Message`
- `CommandType`
- `CommandResult`
- `AppState`

## Dependency Rules
- `MonitorApp` owns `RuntimeContext`.
- `RuntimeContext` owns service instances.
- `ConversationSession` and `ServerApp` use `RuntimeContext` only.
- `CommandProcessor` depends on services, not on module globals.
- No class in `monitor_oop` should read state from `monitor` at runtime.
