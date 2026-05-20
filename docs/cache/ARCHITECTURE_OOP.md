# ARCHITECTURE_OOP

This document describes the overall architecture of `monitor_oop` as it exists today.

## Architectural Intent
`monitor_oop` is an isolated rewrite of Monitor that favors explicit object ownership, small services, and free-function orchestration. The goal is to keep runtime state local to a single application instance while avoiding mutable module globals and hidden cross-package coupling.

The codebase uses a layered style inside `src/monitor_oop/core/` with explicit presentation, application, domain, and infrastructure responsibilities. The longer-term direction is to support an *orchestrator + sub-agent* topology in which a primary instance launches additional `monitor_oop` instances as sub-agents and integrates their results back into its own conversation — see `SUBAGENT_PLAN.md` for the planned IPC and lifecycle.

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
- It holds config, history, macro, status, logging, tool, request-capacity, rate-limit, compaction-store, summarization, command, prompt, and LLM services.
- `PromptService` and `PromptStore` are part of the runtime graph.
- `RequestCapacityService` and `RateLimitService` are part of the runtime graph.
- `CompactionStore` is part of the runtime graph as the forensic-only persistence boundary for compaction summaries.
- `system_prompt` is resolved through `ConfigService` and then persisted or loaded by `PromptStore`.
- `ConfigService` also exposes the compaction configuration used by the conversation/history layer: `summarization_settings.preserve_units` and `summarization_settings.compaction_soft_ratio` drive compaction policy in addition to `token_limit` and `prompt_template`.
- `ConfigService` follows the explicit bootstrap order `config.yaml -> model_config_v2.json -> .env -> system_prompt`, and the committed packaged `model_config_v2.json` file is copied into the user config directory during bootstrap when needed.
- `ConfigService` loads and applies `model_config_v2.json` during bootstrap, and the resolved model fields are carried in `RuntimeConfig`.
- Conversation compaction is owned by the conversation/history layer: `ConversationSession` triggers compaction *before* the LLM call (proactively, not reactively), `HistoryService` owns the compaction decision (soft + hard context-window triggers, with a turn-budget backstop) and the deterministic replacement step, and `SummarizationService` owns LLM-backed summary generation with a deterministic fallback when the LLM call fails.
- `RuntimeContext.status_listener` is an optional callback registered by the presentation layer to receive mid-turn phase transitions (e.g. `"compacting"` → `"working"`); CLI and server paths leave it unset.
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
7. `ConversationSession` appends the user message and evaluates compaction proactively.
8. `LLMService` handles conversational completion.
9. `HistoryService` records conversation messages and tracks the turn budget.
10. Output is rendered back to the user.
11. Rate-limit denials raised as `RateLimitDeniedError` are caught by the REPL loop and surfaced as `[rate limit] <message>` on stdout; the loop continues so the user can wait and retry.

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
3. `TuiApp` creates and owns the `prompt_toolkit` session and registers itself as the `RuntimeContext.status_listener`.
4. Runtime TUI logging is suppressed while the TUI session is active.
5. User input is read through the prompt toolkit layer.
6. Turn execution runs on a worker thread via the `TuiApp` `ThreadPoolExecutor`; the UI thread stays responsive.
7. Phase transitions during a turn (`working` → `compacting` → `working`) are surfaced through the status listener and update the status line immediately via `application.invalidate()`.
8. End-of-turn status is `"completed (idle)"` (green) on success or `"failed (idle)"` (red) on generic failure.
9. Rate-limit denials raised as `RateLimitDeniedError` are surfaced as a red error transcript line containing the full diagnostic plus a yellow `"rate limited (idle)"` status indicator — transient, distinct from fatal red.
10. Output is rendered back to the user.

## LLM Architecture
`LLMRequestBuilder`, `LLMResponseClient`, and `ToolCallHandler` are the collaborators used by `LLMService` to shape requests, invoke the provider, and handle tool calls.

`LLMRequestBuilder.build_input(history)` renders the request from history alone — the caller must ensure the user's latest turn is the final entry in history. The builder also preserves tool-call metadata (`tool_calls`, `tool_call_id`, `name`) on each message so the boundary tracker's preservation of tool-call clusters survives end-to-end through the request layer.

`LLMService.complete(history)` takes only the conversation history; the previously-redundant `user_input` parameter is gone (it was being sent twice in every request via the trailing append in the builder).

`LLMResponseClient.create_response(input_messages, previous_response_id=None, max_output_tokens=None)` runs the request-capacity and rate-limit preflights before adapter dispatch and records usage afterward. The capacity preflight delegates to the canonical `ConfigService.estimate_token_usage` estimator — the same path the rate-limit preflight uses — so both gates evaluate identical numbers. The `max_output_tokens` parameter is plumbed end-to-end into the OpenAI Responses API call so the summarization token cap is real, not a soft string hint.

Extracted collaborators:
- `LLMRequestBuilder` for input shaping (tool-call metadata preserved)
- `LLMResponseClient` for provider invocation (single-shot preflight gates)
- `ToolCallHandler` for tool-call parsing and execution
- `LLMService` for orchestration of the LLM flow

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
- `ConfigService` exposes the compaction configuration used by the conversation/history layer, including `get_compaction_preserve_units()` and `get_compaction_soft_ratio()`. The canonical config name for the settings object is `summarization_settings`; legacy aliases (`summarization`, `compaction_config`) have been removed.
- `ConfigService` exposes `get_model_tpm_limit()` / `get_model_rpm_limit()` returning `int | None`: missing or explicit `0` both mean disabled (treated identically by the rate-limit service). Missing TPM logs a warning and acts as unlimited; missing RPM logs an error and exits the process.
- `ConfigService` follows the explicit bootstrap order `config.yaml -> model_config_v2.json -> .env -> system_prompt`, and the committed packaged `model_config_v2.json` file is copied into the user config directory during bootstrap when needed.
- `ConfigService` loads and applies `model_config_v2.json` during bootstrap, and the resolved model fields are carried in `RuntimeConfig`.
- `HistoryService.compact(summary_text)` performs the replacement step: clear history, append the system summary, append the boundary-aware preserved tail (size controlled by `SummarizationSettings.preserve_units`), and persist the summary best-effort via `CompactionStore`.
- `HistoryService.should_compact(context_window, estimated_token_count, output_window)` evaluates triggers in order: (1) soft context-window — fires when `estimated_token_count >= context_window * compaction_soft_ratio` (default 0.5), (2) hard context-window — fires when input + reserved output ≥ window, (3) turn-budget — fires near the configured turn cliff.
- `ConversationSession._maybe_compact_history` runs *before* the LLM call (proactive). On compaction, the session emits `"compacting"` via the status listener, runs the summarization + replacement, then restores `"working"` in a `try/finally` so the indicator never sticks.
- `SummarizationService` owns LLM-backed summary generation with a clamped output via `max_output_tokens=min(token_limit, output_window)`. On LLM failure or empty response, falls back to a deterministic summary that *carries forward* the prior system summary (capped at `token_limit × 4` chars, truncating accumulated placeholder lines first) plus a new placeholder line. Monotonic across repeated failures, bounded against unbounded growth.
- `CompactionStore` is forensic-only: nothing in the runtime reads `compact-*.summary` files back. Files use `YYYY-MM-DD-HH-MM-SS` timestamps with `-N` collision counters and exclusive-create writes (race-safe). Files older than 30 days are swept on each successful save.
- `PromptService` owns prompt resolution and the runtime prompt file lifecycle through explicitly injected collaborators.
- `PromptStore` persists the system prompt at `appdirs.user_config_dir("monitor")/system_prompt` and seeds it from `system_prompt.example` on first run.

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

## Rate Limiting and Capacity
`RateLimitService` is a *pure admission-control gate*. `check_request(model, estimated_tokens)` returns on success and raises `RateLimitDeniedError` on denial, carrying structured fields (`reason`, `model`, `current`, `limit`, `retry_after_seconds`). The decision of what to do on denial — raise, retry, queue — belongs to the caller. The REPL catches and prints; the TUI catches and surfaces with a yellow `"rate limited (idle)"` indicator + red transcript line.

The service is model-keyed with normalized accounting keys (provider prefix stripped, lowercased), so `"openai/gpt-4o"` and `"gpt-4o"` share a budget. Wait-mode plumbing (`allow_wait`, `wait_timeout_seconds`, polling loop) has been removed; if queue-and-wait semantics are needed for an agent-orchestrator scenario, the recommended path is a separate `RateLimitedScheduler` layer that wraps this gate — keep the gate stateless.

`RateLimitService.estimate_token_usage` is *chain-aware*: when `previous_response_id` matches a cached prior response, it adds that response's `total_tokens` as a baseline to the local marginal estimate, so the preflight reflects the full server-side context the provider will process. The cache is a bounded LRU keyed by `response.id`, populated from `response.usage.total_tokens` on every successful request.

`RequestCapacityService.evaluate_request` delegates token estimation to the canonical `ConfigService.estimate_token_usage` — the same path the rate-limit gate uses — so both preflights evaluate identical numbers. The capacity check is the per-call context-window fit test; the rate-limit check is the rolling-window throughput budget.

## Current Direction
The architecture is stable. The next major expansion is the orchestrator + sub-agent topology — see `SUBAGENT_PLAN.md`. Required additions to the architecture for that work:
- a `SubagentService` and `SubagentRunner` in `infrastructure/` for subprocess management and JSON-Lines IPC over stdin/stdout
- a `spawn_subagent` tool registered on the orchestrator's tool registry only
- a richer status representation (per-agent state instead of a single `status_text` string)
- an event-queue drain that fires on every redraw tick (currently drains only on background completion)

## Rules of Thumb
- `build_app()` owns construction during bootstrap.
- `RuntimeContext` stores references to the process-local service graph and supports an optional `status_listener` callback for the presentation layer.
- Dependency creation is explicit at the composition root.
- Prompt, config, and LLM boundaries remain stable and explicit.
- `MonitorApp` delegates TUI startup to `TuiApp`.
- `build_app()` supports quiet bootstrap for TUI mode.
- Runtime TUI logging remains suppressed while the TUI session is active.
- `RateLimitService` is a gate, not a scheduler — wait/queue semantics live above it.
- Tests assert on the public interface only — no private (`_`-prefixed) attribute or method access in tests.
