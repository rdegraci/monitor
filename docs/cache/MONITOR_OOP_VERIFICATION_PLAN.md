# MONITOR_OOP_VERIFICATION_PLAN

This document defines how the isolated Monitor rewrite is validated against the legacy app as the thin-slice implementation stands today. See `ARCHITECTURE_OOP.md` for the architecture overview alongside these verification notes.

## Verification Goals
- Confirm the new app runs independently for the current thin-slice CLI path.
- Confirm the classic CLI REPL remains the default interactive mode, while the prompt_toolkit TUI is available through the separate `--tui` path.
- Confirm the new app does not mutate legacy mutable globals during the covered flows.
- Confirm behavior is stable for the first thin-slice implementation.
- Confirm CLI, script, TUI, and server flows work in the new package where they are currently implemented.
- Confirm the new app preserves intended user-visible behavior where required.
- Confirm logging is configured once at bootstrap through `LoggerService`, runtime modules use standard logger access patterns without reconfiguring global logging state, the default REPL logs to screen and file, and the `--tui` path uses file-only logging without screen output.
- Confirm quiet bootstrap is used for TUI startup, and runtime TUI logging uses file-only logging without screen output while the TUI is active as current verified behavior.
- Confirm the TUI status line renders green when idle and yellow when working.
- Confirm configuration bootstrap behavior for `monitor_oop` is implemented and verified: `ConfigLoader` preserves existing `appdirs.user_config_dir("monitor")/config.yaml` files, seeds only missing files from `src/monitor_oop/config.yaml.example` into the user config directory when needed, `EnvLoader` loads `.env` with `find_dotenv(usecwd=True)` plus user config fallbacks, and `ConfigService` acts as a façade that resolves the persistent prompt history path with an `appdirs`-first lookup and `~/.config/monitor/` fallback while continuing to use `prompt_toolkit.PromptSession` with `FileHistory`.
- Confirm prompt loading behavior is implemented and verified: `system_prompt` is loaded from `appdirs.user_config_dir("monitor")/system_prompt`, seeded from `system_prompt.example` on first run, and injected as the first system message in request construction.
- Confirm `LLMRequestBuilder` has dedicated tests under `tests/monitor_oop/core/application/test_llm_request_builder.py`, and request shaping is verified separately from `LLMService`.
- Confirm `LLMResponseClient` has dedicated tests under `tests/monitor_oop/core/application/test_llm_response_client.py`, and provider-boundary behavior is verified separately from `LLMService`.
- Confirm `ToolCallHandler` has dedicated tests, and tool-call execution behavior is verified separately from `LLMService`.
- Confirm `LLMService` tests are isolated from the real provider boundary and exercise only the service-level contract with controlled test doubles.
- Confirm `LLMService` tests are isolated from tool-execution internals because tool handling is now covered separately.
- Confirm tool calling is verified for detection, normalization, execution, and follow-up payload construction using the new isolated registry/service design, isolated from legacy global tool registries or mutable shared state.
- Confirm tool-calling verification now has a concrete tool package to exercise (`src/monitor_oop/core/tools/`), including the deterministic weather tool, registry/service boundaries, and parsing helpers.
- Confirm tool calling is verified through direct `response.output` parsing with `extract_tool_calls`, multi-tool single-turn scenarios, batched follow-up payload submission with matching `call_id` values, richer tool parsing coverage focused on Responses API shapes, a defensive 16-call tool-loop cap, and the current `LLMService` multi-call handling.
- Confirm tool turn state is owned by the dedicated `ToolTurnState` helper with turn-scoped lifecycle management, including tool call accumulation, follow-up preparation, and cleanup at the end of each turn.
- Confirm real LLM behavior remains a future work item.
- Confirm current LLM safeguards are covered, including defensive finish-reason handling and the 16-call tool-loop cap.
- Confirm adjusted tests assert the present tool-calling behavior as implemented today.
- Confirm macro subsystem verification targets recursive macro expansion, delimiter-aware escaping, JSON-backed macro loading/saving as parity goals, and prompt-specific docs alignment alongside those goals.
- Confirm TCL macro behavior is tracked separately if it is not yet implemented.
- Confirm TUI verification covers visible working status during submission, output/status updates after background completion, no direct widget-state mutation from worker threads, and the ability to reuse the same background turn pattern for future subagents.

## Verification Scope
### Startup
- App can be instantiated without importing legacy runtime state.
- App can load its own config, including the fallback `~/.config/monitor/.env`, and construct its runtime context.
- App can start and stop cleanly.
- Logging is initialized once during bootstrap via `LoggerService`, and application modules obtain loggers through standard logger access patterns.
- Quiet bootstrap is used for TUI startup, and the active TUI uses file-only logging without screen output while it is displayed as current verified behavior.
- The TUI status line renders green when idle and yellow when working.
- Configuration bootstrap behavior for `monitor_oop` is covered by verification: `ConfigLoader` preserves existing `appdirs.user_config_dir("monitor")/config.yaml` files, seeds only missing files from `src/monitor_oop/config.yaml.example` into the user config directory when needed, `EnvLoader` loads `.env` with `find_dotenv(usecwd=True)` plus user config fallbacks, and `ConfigService` acts as a façade that resolves the persistent prompt history path with an `appdirs`-first lookup and `~/.config/monitor/` fallback while continuing to use `prompt_toolkit.PromptSession` with `FileHistory`.
- Prompt loading behavior is covered by verification: `system_prompt` is loaded from `appdirs.user_config_dir("monitor")/system_prompt`, seeded from `system_prompt.example` on first run, and injected as the first system message in request construction.
- Verification tests now live under `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/`, mirroring the production package structure.
- Current tests and the runnable CLI partially verify startup behavior.

### Conversation Flow
- Prompt creation works.
- One input cycle can be processed.
- Exit handling works.
- Command dispatch uses the new command processor.
- Runtime conversation modules use standard logger access patterns without direct logging bootstrap responsibility.
- The default interactive experience is the classic CLI REPL, and the prompt_toolkit TUI is exercised only through the dedicated `--tui` path.
- Current tests and the runnable CLI partially verify conversation flow.

### Server Flow
- Flask app can be created from the new runtime context.
- Request handling uses only new app services.
- API responses are structurally correct.
- Server flow remains future work beyond the current thin-slice coverage.
- Server-side modules use standard logger access patterns, with logging configured once at bootstrap.

### Isolation
- Legacy module globals are not read or written during new app runtime.
- No shared mutable state exists between packages.
- New app services own their state instance-local.
- Logger configuration is centralized and performed once at bootstrap; runtime modules only acquire loggers through standard access patterns.
- Current tests and the runnable CLI partially verify isolation behavior.
- TUI startup uses quiet bootstrap, and TUI runtime uses file-only logging without screen output while the TUI is active as current verified behavior.
- The per-process log file convention writes to the user config directory `log/` subdirectory with `monitor_<pid>.log`.

### Tool Turn State
- Tool turn state is encapsulated in `ToolTurnState` rather than being managed ad hoc inside LLM/service code.
- Tool turn lifecycle is turn-scoped, with state created at the start of a tool-enabled turn and cleared after the turn completes.
- Tool call tracking, pending follow-up payload preparation, and multi-call sequencing are verified through the dedicated helper.
- Current tests assert that the helper owns the per-turn tool state and that no stale tool turn state leaks across turns.
- Background TUI turns reuse the same turn-state pattern for future subagent-style work, while keeping widget updates out of worker threads.

### TUI Background Turn Handling
- Visible working status is shown during submission so the user can see that the active turn is in progress.
- Output and status are updated after background completion so the TUI reflects the final result of the submitted turn.
- Worker threads do not mutate widget state directly, and UI changes happen through the appropriate handoff back to the TUI layer.
- The same background turn pattern can be reused for future subagents without introducing new shared mutable state.

## Test Categories
- Unit tests for services and helpers.
- Integration tests for app startup and session flow.
- Integration tests for server routes.
- Regression comparisons against legacy behavior for key workflows.
- Isolation tests to ensure separation from `src/monitor_oop/core/`.
- Verification tests live under `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/`, mirroring the production package structure.
- Prompt-loading tests for `system_prompt` seeding, loading, and request injection behavior.

## Suggested Verification Order
1. Startup tests.
2. Config service tests.
3. Command processor tests.
4. Conversation session tests.
5. Server tests.
6. Isolation tests.
7. Regression comparison tests.
8. Tool turn state tests.
9. TUI background turn handling tests.

## Pass Criteria
- No test depends on legacy mutable globals.
- The thin-slice CLI path passes end to end.
- Server mode passes basic route and response tests where implemented.
- Core behaviors match legacy expectations where intentionally preserved.
- Real LLM behavior is deferred until the corresponding implementation exists.
- Tool calling passes OpenAI Responses API finish-reason handling, deterministic weather tool execution, direct `response.output` parsing via `extract_tool_calls`, multi-tool single-turn batching, matching `call_id` follow-up payload submission, richer tool parsing coverage focused on Responses API shapes, the defensive 16-call tool-loop cap, and the current `LLMService` multi-call handling.
- Tool turn state is owned by `ToolTurnState`, and per-turn lifecycle management prevents leakage across turns.
- Logging is configured once at bootstrap via `LoggerService`, the default REPL logs to screen and file, and the `--tui` path uses file-only logging without screen output.
- The classic CLI REPL remains the default interactive mode, the `--tui` path activates the prompt_toolkit TUI, TUI startup uses quiet bootstrap, and runtime TUI uses file-only logging without screen output while the TUI is active.
- The TUI status line renders green when idle and yellow when working.
- TUI verification covers visible working status during submission, output/status updates after background completion, no direct widget-state mutation from worker threads, and reuse of the same background turn pattern for future subagents.

## Failure Handling
- Treat any accidental mutation of legacy globals as a blocking issue.
- Treat any cross-package state leakage as a blocking issue.
- Treat behavior changes as acceptable only when explicitly documented.
