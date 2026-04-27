# MONITOR_OOP_VERIFICATION_PLAN

This document defines how the isolated Monitor rewrite is validated against the legacy app as the thin-slice implementation stands today.

## Verification Goals
- Confirm the new app runs independently for the current thin-slice CLI path.
- Confirm the new app does not mutate legacy mutable globals during the covered flows.
- Confirm behavior is stable for the first thin-slice implementation.
- Confirm CLI, script, and server flows work in the new package where they are currently implemented.
- Confirm the new app preserves intended user-visible behavior where required.
- Confirm logging is configured once at bootstrap through `LoggerService`, and runtime modules use standard logger access patterns without reconfiguring global logging state.
- Confirm tool calling is verified for detection, normalization, execution, and follow-up payload construction using the new isolated registry/service design, isolated from legacy global tool registries or mutable shared state.
- Confirm tool-calling verification now has a concrete tool package to exercise (`src/monitor_oop/core/tools/`), including the deterministic weather tool, registry/service boundaries, and parsing helpers.
- Confirm tool calling is verified through multi-tool single-turn scenarios, batched follow-up payload submission with matching `call_id` values, richer tool parsing, a defensive 16-call tool-loop cap, and the current `LLMService` multi-call handling.
- Confirm real LLM behavior remains a future work item.
- Confirm current LLM safeguards are covered, including defensive finish-reason handling and the 16-call tool-loop cap.
- Confirm adjusted tests assert the present tool-calling behavior as implemented today.

## Verification Scope
### Startup
- App can be instantiated without importing legacy runtime state.
- App can load its own config, including the fallback `~/.config/monitor/.env`, and construct its runtime context.
- App can start and stop cleanly.
- Logging is initialized once during bootstrap via `LoggerService`, and application modules obtain loggers through standard logger access patterns.
- Current tests and the runnable CLI partially verify startup behavior.

### Conversation Flow
- Prompt creation works.
- One input cycle can be processed.
- Exit handling works.
- Command dispatch uses the new command processor.
- Runtime conversation modules use standard logger access patterns without direct logging bootstrap responsibility.
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

## Test Categories
- Unit tests for services and helpers.
- Integration tests for app startup and session flow.
- Integration tests for server routes.
- Regression comparisons against legacy behavior for key workflows.
- Isolation tests to ensure separation from `src/monitor_oop/core/`.

## Suggested Verification Order
1. Startup tests.
2. Config service tests.
3. Command processor tests.
4. Conversation session tests.
5. Server tests.
6. Isolation tests.
7. Regression comparison tests.

## Pass Criteria
- No test depends on legacy mutable globals.
- The thin-slice CLI path passes end to end.
- Server mode passes basic route and response tests where implemented.
- Core behaviors match legacy expectations where intentionally preserved.
- Real LLM behavior is deferred until the corresponding implementation exists.
- Tool calling passes OpenAI Responses API finish-reason handling, deterministic weather tool execution, multi-tool single-turn batching, matching `call_id` follow-up payload submission, richer tool parsing, the defensive 16-call tool-loop cap, and the current `LLMService` multi-call handling.
- Logging is configured once at bootstrap via `LoggerService`, and runtime modules use standard logger access patterns.

## Failure Handling
- Treat any accidental mutation of legacy globals as a blocking issue.
- Treat any cross-package state leakage as a blocking issue.
- Treat behavior changes as acceptable only when explicitly documented.
