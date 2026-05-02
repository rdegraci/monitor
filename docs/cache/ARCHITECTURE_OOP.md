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
- planned extracted LLM collaborators such as request building and completion coordination

Responsibilities:
- decide which workflow runs
- coordinate command processing
- coordinate LLM completion and tool handling
- move data between services without owning low-level integration details

### Domain
The domain layer contains the core application concepts and rules.

Current examples:
- `models.py`
- `History`
- `ToolTurnState`
- command and message model objects

Responsibilities:
- model app state and results
- represent messages, commands, tool state, and runtime config
- keep business rules independent from transport and persistence details

### Infrastructure
The infrastructure layer handles external systems and technical integration.

Current examples:
- `ConfigService`
- `HistoryService`
- `LoggerService`
- `ToolRegistry`
- `ToolService`
- `ResponsesLiteLLMAdapter`
- future extracted LLM response client

Responsibilities:
- load config from environment, YAML, and user paths
- persist or recover history
- integrate with logging
- execute tools
- talk to external model providers

## Runtime Object Graph
The runtime is composed explicitly at startup.

### Root coordinator
- `MonitorApp` is the top-level entry point.
- It owns a `RuntimeContext` and selects the workflow to run.

### RuntimeContext
- `RuntimeContext` owns the process-local service graph.
- It holds config, history, macro, status, logging, tool, command, and LLM services.
- It acts as the explicit wiring point for CLI, server, and script modes.

### Session and server entry points
- `ConversationSession` owns one interactive CLI session.
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
8. `HistoryService` records conversation messages.
9. Output is rendered back to the user.

## Server Flow
The server flow follows the same runtime ownership model.

1. `MonitorApp` selects server mode.
2. `RuntimeContext` is reused.
3. `ServerApp` creates or exposes the HTTP application.
4. Requests are converted into command or message inputs.
5. Application services perform the work.
6. Responses are returned through the HTTP boundary.

## LLM Architecture
`LLMRequestBuilder` and `LLMResponseClient` have already been extracted into separate collaborators. `LLMService` now coordinates request shaping, provider invocation, and completion orchestration through these collaborators rather than directly owning provider calls.

Extracted collaborators:
- `LLMRequestBuilder` for input shaping
- `LLMResponseClient` for provider invocation
- `ToolCallHandler` for tool-call parsing and execution
- `ResponseCompletionCoordinator` for finish-reason handling and tool-loop policy

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

The tool flow is intentionally modeled as a turn-scoped workflow rather than a global mutable cache.

## Configuration and History
Configuration and history are handled as runtime-owned services.

- `ConfigService` loads config from YAML, `.env`, and environment variables.
- It resolves the persistent prompt history file path from config.
- `HistoryService` owns the conversation history domain object.
- `ConversationSession` uses prompt history through the prompt toolkit layer, but does not own the persistence details itself.

## Logging
Logging is initialized once during bootstrap.

- `LoggerService` owns logging setup.
- Runtime modules use standard `logging.getLogger(__name__)` access patterns.
- Logging configuration is not duplicated across feature modules.

## Test Layout
The tests mirror the source tree.

Current structure:
- `tests/monitor_oop/core/`
- `tests/monitor_oop/core/tools/`

This keeps tests close to the implementation and makes refactors easier to track.

## Current Direction
The codebase is moving toward:
- clearer presentation boundaries
- more explicit application orchestration
- smaller LLM collaborators
- stable domain objects
- infrastructure isolated behind narrow interfaces

The current implementation is already usable, but the architecture is still evolving toward a cleaner layered design.
