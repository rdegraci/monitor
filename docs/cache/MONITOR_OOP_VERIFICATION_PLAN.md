# MONITOR_OOP_VERIFICATION_PLAN

This document defines how the isolated Monitor rewrite will be validated against the legacy app.

## Verification Goals
- Confirm the new app runs independently.
- Confirm the new app does not mutate legacy mutable globals.
- Confirm behavior is stable for the first thin-slice implementation.
- Confirm CLI, script, and server flows work in the new package.
- Confirm the new app preserves intended user-visible behavior where required.

## Verification Scope
### Startup
- App can be instantiated without importing legacy runtime state.
- App can load its own config and construct its runtime context.
- App can start and stop cleanly.

### Conversation Flow
- Prompt creation works.
- One input cycle can be processed.
- Exit handling works.
- Command dispatch uses the new command processor.

### Server Flow
- Flask app can be created from the new runtime context.
- Request handling uses only new app services.
- API responses are structurally correct.

### Isolation
- Legacy module globals are not read or written during new app runtime.
- No shared mutable state exists between packages.
- New app services own their state instance-local.

## Test Categories
- Unit tests for services and helpers.
- Integration tests for app startup and session flow.
- Integration tests for server routes.
- Regression comparisons against legacy behavior for key workflows.
- Isolation tests to ensure separation from `src/monitor/`.

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
- Server mode passes basic route and response tests.
- Core behaviors match legacy expectations where intentionally preserved.

## Failure Handling
- Treat any accidental mutation of legacy globals as a blocking issue.
- Treat any cross-package state leakage as a blocking issue.
- Treat behavior changes as acceptable only when explicitly documented.
