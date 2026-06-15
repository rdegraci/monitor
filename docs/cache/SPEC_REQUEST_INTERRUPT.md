# SPEC_REQUEST_INTERRUPT

## Summary
This document defines desired behavior for request interruption, cancellation, and provider-failure handling as it relates to turn history and protocol integrity.

## Terminology
### Submitted turn
A turn whose user input has been sent into processing after the user pressed Return/submit.

### Uncommitted turn
A submitted turn for which no valid assistant response or protocol state has yet been durably committed.

### Partially committed turn
A submitted turn for which some protocol state has been committed, such as assistant tool-call messages or tool result messages, but which has not yet completed as a normal assistant reply.

### Committed turn
A turn that has produced a coherent assistant or refusal outcome suitable for durable history.

### Interrupted turn
A submitted turn whose processing was cancelled or failed after submission.

## Requirements
### R1. Pre-submit cancellation
If the user cancels before submit, no conversation history mutation must occur.

### R2. Uncommitted-turn rollback
If a submitted turn fails or is cancelled before any committed assistant/protocol state exists, the system should rollback the user turn and any matching per-turn accounting state.

### R3. Structured refusal behavior
If the provider returns a valid refusal/content-filter/safety response, the triggering user turn should not remain as a normal conversational turn.

### R4. Partial protocol preservation
If assistant tool-call or tool-result protocol state has already been committed, the system must preserve or repair minimal coherent protocol state rather than blindly removing the last user turn.

### R5. Ledger consistency
Any rollback of a user turn must keep per-turn accounting structures synchronized with conversation history.

### R6. Retry hygiene
After interruption or generic provider failure, retrying the request should not duplicate stale failed-turn context.

### R7. Front-end parity
REPL and TUI should obey the same history semantics for submit, cancellation, interruption, and generic request failure.

## Expected behavior by class
### Generic provider failure before commit
Examples:
- HTTP 401
- HTTP 403
- HTTP 429
- HTTP 5xx
- timeout
- network error
- malformed request before valid response object

Expected behavior:
- treat as interrupted uncommitted turn
- rollback user turn
- rollback matching per-turn accounting

### Structured refusal response
Examples:
- refusal
- content_filter
- safety

Expected behavior:
- remove offending user turn from normal conversation history
- remove matching per-turn accounting bucket(s)

### Normal completion
Example:
- assistant response with normal completion

Expected behavior:
- preserve user turn
- preserve assistant turn
- preserve accounting

### Partial tool-call commit followed by failure or cancel
Expected behavior:
- preserve minimal coherent protocol state
- avoid orphaned tool-call history
- do not apply naive last-user-message rollback

## Non-requirements
- undoing already-executed side effects of tools
- forcing server-mode request cancellation semantics into scope immediately
- redesigning all history-building logic if a smaller rollback/repair model suffices

## Validation criteria
A compliant implementation should demonstrate:
1. pre-submit cancel leaves no history changes
2. generic 4xx/5xx failure before commit does not pollute context history
3. post-submit cancellation before commit does not pollute context history
4. refusal handling preserves its semantic cleanup behavior
5. tool-call interruption does not leave malformed protocol state
6. retries after interruption or failure do not compound stale context
