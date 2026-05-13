# ARCHITECTURE_OOP

This document describes the overall architecture of `monitor_oop` as it exists today and the direction it is moving toward.

## Architectural Intent
`monitor_oop` is an isolated rewrite of Monitor that favors explicit object ownership, small services, and free-function orchestration. The goal is to keep runtime state local to a single application instance while avoiding mutable module globals and hidden cross-package coupling.

The codebase currently uses a pragmatic layered style inside `src/monitor_oop/core/`, and it is gradually becoming more explicit about presentation, application, domain, and infrastructure responsibilities.

## High-Level Layers

### Presentation
The presentation layer owns terminal or HTTP interaction with the user.

Current examples:
- `ConversationSession` for CLI interaction
- `TuiApp` for the `prompt_toolkit`-based TUI implementation
- `ServerApp` for HTTP entry points

Responsibilities:
- collect user input
- render output
- manage user-facing session flow
- keep UI concerns out of business logic

### Application
The application layer coordinates use cases and orchestrates work between services.

Current examples:
- `MonitorApp`
- `workflow.py`
- `CommandProcessor`
- `LLMService`
- `PromptService`
- `PromptStore`
- `RequestCapacityService`
- `RateLimitService`
- the macro subsystem, which is loaded during bootstrap by `MacroService` and delegates persistence to `MacroStore` and expansion to `MacroExpander`, while further legacy parity work may still be needed for delimiter, escape, and TCL behavior
- `TuiApp`, which is Application-backed and owns the prompt_toolkit TUI flow

Responsibilities:
- decide which workflow runs
- coordinate command processing
- coordinate LLM completion and tool handling
- coordinate prompt loading and resolution
- move data between services without owning low-level integration details

### Domain
The domain layer contains the core application concepts and rules.

Current examples:
- `models.py`
- `History`
- `ToolTurnState`
- `RuntimeConfig`
- command and message model objects

Responsibilities:
- model app state and results
- represent messages, commands, tool state, runtime config, and runtime settings
- keep business rules independent from transport and persistence details

### Infrastructure
The infrastructure layer handles external systems and technical integration.

Current examples:
- `ConfigService`
- `HistoryService`
- `LoggerService`
- `PromptStore`
- `ToolRegistry`
- `ToolService`
- `ResponsesOpenAiAdapter`
- future extracted LLM response client

Responsibilities:
- load config from environment, YAML, and user paths
- persist or recover history
- load and seed the system prompt from `appdirs.user_config_dir("monitor")/system_prompt`, initializing it from `system_prompt.example` on first run
- integrate with logging
- execute tools
- talk to external model providers

## Runtime Object Graph
The runtime is composed explicitly at startup.

### Root coordinator
- `MonitorApp` is the top-level entry point.
- It owns a `RuntimeContext` and selects the workflow to run.
- `MonitorApp` delegates TUI startup to the Application-backed `TuiApp`.
- `MonitorApp` exposes read-only accessors over its privately stored dependencies.

### RuntimeContext
- `RuntimeContext` owns the process-local service graph.
- It is constructed with explicit dependencies and stores the services needed by the application.
- It exposes read-only accessors over its privately stored dependencies.
- It holds config, history, macro, status, logging, tool, request-capacity, rate-limit, command, prompt, and LLM services.
- `PromptService` and `PromptStore` are part of the runtime graph.
- `RequestCapacityService` and `RateLimitService` are part of the runtime graph.
- `system_prompt` is resolved through `ConfigService` and then persisted or loaded by `PromptStore`.
- `ConfigService` also exposes the compaction configuration used by the conversation/history layer.
- `ConfigService` follows the explicit bootstrap order `config.yaml -> model_config_v2.json -> .env -> system_prompt`, and the committed packaged `model_config_v2.json` file is copied into the user config directory during bootstrap when needed.
- `ConfigService` loads and applies `model_config_v2.json` during bootstrap, and the resolved model fields are carried in `RuntimeConfig`.
- Conversation compaction is owned by the conversation/history layer: `ConversationSession` triggers deterministic compaction, `HistoryService` owns turn-budget tracking and compaction replacement, and `SummarizationService` owns LLM-backed summary generation using the configured prompt template and history contents.
- It acts as the explicit wiring point for CLI, server, and script modes.

### Session and server entry points
- `ConversationSession` owns one interactive CLI session.
- `TuiApp` owns the `prompt_toolkit`-based TUI session lifecycle.
- `ServerApp` owns HTTP startup and request conversion.
- Both use the shared `RuntimeContext` instead of reaching into globals.

## CLI Flow
A typical CLI flow looks like this:

1. `build_app()` creates the runtime services.
2. `MonitorApp` receives the context.
3. `workflow.run_cli()` creates a session.
4. `ConversationSession.start()` marks the session running.
5. User input is read through the prompt layer.
6. `CommandProcessor` classifies commands.
7. `LLMService` handles conversational completion.
8. `HistoryService` records conversation messages, tracks the turn budget, and performs conversation compaction in the conversation/history layer.
9. Output is rendered back to the user.

## Server Flow
The server flow follows the same runtime ownership model.

1. `MonitorApp` selects server mode.
2. `RuntimeContext` is reused.
3. `ServerApp` creates or exposes the HTTP application.
4. Requests are converted into command or message inputs.
5. Application services perform the work.
6. Responses are returned through the HTTP boundary.

## TUI Flow
The TUI flow follows the same runtime ownership model with `prompt_toolkit`.

1. `build_app()` supports quiet bootstrap for TUI mode.
2. `MonitorApp` delegates TUI startup to `TuiApp`.
3. `TuiApp` creates and owns the `prompt_toolkit` session.
4. Runtime TUI logging is suppressed while the TUI session is active.
5. User input is read through the prompt toolkit layer.
6. Command and message inputs are routed through application services.
7. The TUI is moving toward background turn execution for LLM submissions so the status line can visibly show working while the request is in flight.
8. Output is rendered back to the user.

## LLM Architecture
`LLMRequestBuilder`, `LLMResponseClient`, and `ToolCallHandler` are the collaborators used by `LLMService` to shape requests, invoke the provider, and handle tool calls.

`LLMRequestBuilder` accepts explicit prompt text and prepends it as the first system message before appending the conversational context. It no longer consults `PromptService` directly.

`LLMService` keeps its response adapter private and uses it only through internal orchestration.

Extracted collaborators:
- `LLMRequestBuilder` for input shaping
- `LLMResponseClient` for provider invocation
- `ToolCallHandler` for tool-call parsing and execution
- `LLMService` for orchestration of the LLM flow

The desired result is:
- `LLMService` acts as a façade
- input shaping stays separate from provider access
- tool handling stays separate from orchestration policy
- adapter calls stay isolated from application flow

## Tooling Architecture
Tools are managed through a dedicated registry and service boundary.

- `ToolRegistry` stores registered tools and metadata.
- `ToolService` executes registered tools.
- `ToolTurnState` tracks per-turn tool envelopes and follow-up work.
- Parsing helpers remain free functions where that keeps the code simpler and easier to test.
- The macro subsystem is loaded during bootstrap by `MacroService` and delegates persistence to `MacroStore` and expansion to `MacroExpander`, while further legacy parity work may still be needed for delimiter, escape, and TCL behavior.

The tool flow is intentionally modeled as a turn-scoped workflow rather than a global mutable cache.

## Configuration and History
Configuration and history are handled as runtime-owned services.

- `ConfigService` is a façade over `ConfigLoader` and `EnvLoader`.
- `ConfigLoader` owns YAML bootstrap, loading, and validation.
- `EnvLoader` owns dotenv loading and environment overrides.
- `ConfigService` resolves the persistent prompt history file path using appdirs-first, then falls back to `~/.config/monitor`.
- `ConfigService` exposes the compaction configuration used by the conversation/history layer.
- `ConfigService` follows the explicit bootstrap order `config.yaml -> model_config_v2.json -> .env -> system_prompt`, and the committed packaged `model_config_v2.json` file is copied into the user config directory during bootstrap when needed.
- `ConfigService` loads and applies `model_config_v2.json` during bootstrap, and the resolved model fields are carried in `RuntimeConfig`.
- `HistoryService` owns the conversation history domain object.
- `HistoryService` owns turn-budget tracking and compaction replacement.
- `ConversationSession` uses prompt history through the prompt toolkit layer and triggers deterministic compaction when the configured budget is reached.
- `ConversationSession` builds the summary text deterministically from the configured prompt template and history contents.
- `SummarizationService` owns LLM-backed summary generation.
- `PromptService` owns prompt resolution and the runtime prompt file lifecycle through explicitly injected collaborators.
- `PromptStore` persists the system prompt at `appdirs.user_config_dir("monitor")/system_prompt` and seeds it from `system_prompt.example` on first run.
- Conversation compaction is owned by the conversation/history layer.

## Logging
Logging is initialized once during bootstrap.

- `LoggerService` owns logging setup.
- Runtime modules use standard `logging.getLogger(__name__)` access patterns.
- Logging configuration is not duplicated across feature modules.
- Runtime TUI logging is suppressed while the TUI session is active.

## Test Layout
The tests mirror the source tree.

Current structure:
- `tests/monitor_oop/core/`
- `tests/monitor_oop/core/tools/`
- prompt-focused tests and import-path coverage for the prompt subsystem

This keeps tests close to the implementation and makes refactors easier to track.

## Current Direction
The codebase is moving toward:
- clearer presentation boundaries
- more explicit application orchestration
- smaller LLM collaborators
- stable domain objects
- infrastructure isolated behind narrow interfaces
- a consolidated `prompt_toolkit`-based TUI presentation path
- background turn execution for TUI LLM submissions so the status line can visibly show working while the request is in flight

## Rules of Thumb
- `build_app()` still owns construction during bootstrap.
- `RuntimeContext` stores references to the process-local service graph.
- Dependency creation should be explicit at the composition root.
- Ownership is the next refactor target.
- Prompt, config, and LLM boundaries should remain stable and explicit.
- `MonitorApp` delegates TUI startup to `TuiApp`.
- `build_app()` supports quiet bootstrap for TUI mode.
- Runtime TUI logging should remain suppressed while the TUI session is active.

The current implementation is already usable, but the architecture is still evolving toward a cleaner layered design.
