# PLAN_REQUEST_INTERRUPT

## Goal
Define an implementation approach for request interruption and turn-cancellation handling so Monitor preserves coherent conversation history and protocol state when an in-flight request is cancelled or fails.

## Problem statement
Monitor currently appends the user turn into conversation history before the initial LLM request completes. This keeps prompt assembly simple, but it means some failed or cancelled turns can remain in history even when no valid assistant turn was committed.

This becomes visible in cases such as:
- user presses Return and then cancels with Ctrl-C
- user presses Return and then cancels with Esc when the UI supports in-flight cancellation
- provider/network failure before a valid response object is returned
- HTTP 4xx/5xx returned before any committed assistant result exists

The desired behavior is not a blanket pop-on-error rule. Some flows, especially tool-calling flows, may already have committed assistant or tool protocol messages that must be preserved or repaired instead of naively removed.

## Design principle
Treat a user turn like a transaction:
- start turn
- stage or record the user intent
- commit only when a coherent conversational state exists
- rollback when the turn aborts before commit
- preserve or repair minimal coherent protocol state when partial commit already happened

## Key invariants
1. Conversation history should represent coherent committed state.
2. A cancelled or transport-failed turn should not usually remain in history if no assistant/protocol state was committed.
3. Tool-call protocol history must never be left orphaned or malformed.
4. Per-turn accounting structures must stay in sync with conversation history.
5. Interrupt handling must not corrupt history even when cancellation races with a late provider response.

## Scope
In scope:
- REPL request interruption
- TUI request interruption
- provider failures before committed assistant state
- interaction with per-turn cost/round-trip ledgers
- interaction with tool-call protocol history

Out of scope:
- full undo of side-effecting tools after they already ran
- redesign of prompt assembly architecture beyond turn lifecycle handling
- server-side HTTP endpoint cancellation semantics unless explicitly added later

## Proposed lifecycle model
### Phase 1: pre-submit
The user is editing input. Esc or Ctrl-C before submit should leave no conversation history changes.

### Phase 2: submitted but uncommitted
The user message has entered processing, but no assistant/protocol state has been durably committed.

If interruption or transport failure occurs here:
- rollback the user turn
- rollback matching per-turn accounting bucket(s)
- leave prior history unchanged

### Phase 3: partially committed protocol state
The system has appended assistant tool-call state and possibly tool result messages, but no final assistant reply exists.

If interruption or provider failure occurs here:
- do not blindly pop the last user turn
- preserve or repair the minimal coherent protocol state
- ensure no orphaned tool calls remain
- represent the state as interrupted rather than completed if needed

### Phase 4: committed assistant turn
A normal assistant response or valid refusal state exists.

If interruption occurs after this point, history should remain consistent with the committed state already reached.

## Error-policy expectations
### Rollback candidates
These should generally rollback the just-submitted user turn when no committed assistant/protocol state exists:
- HTTP 401
- HTTP 403
- HTTP 429
- HTTP 5xx
- network errors
- timeout errors
- user cancellation via Ctrl-C after submit
- user cancellation via Esc after submit
- malformed request failures before any valid response object is produced

### Preserve-or-repair candidates
These should preserve minimal coherent state instead of using naive rollback:
- assistant tool-call message already appended
- tool result messages already appended
- interruption during tool execution after protocol state commit
- side-effecting tool already executed

### Special-case refusal behavior
Refusal/content-filter/safety responses should keep their existing semantic behavior of removing the offending user turn rather than preserving it as a normal conversation event.

## Implementation outline
1. Identify the boundary between staged user turn and committed turn.
2. Define a single interrupt/failure policy used by REPL and TUI.
3. Separate generic transport/provider failure handling from structured refusal handling.
4. Track whether a turn has committed assistant/protocol state.
5. Apply rollback only when the turn is still uncommitted.
6. Reuse existing tool-call orphan-prevention logic for partial-commit cases.
7. Keep per-turn ledgers synchronized with any rollback action.
8. Verify cancellation race cases where a provider response arrives after the user already requested cancellation.

## Open questions
1. Should the user message be staged outside durable history until first successful provider acknowledgment, or should current eager-append behavior remain with explicit rollback on failure?
2. How should interrupted tool-call turns be represented for debugging and UX purposes?
3. Should cancelled turns produce a visible local-only event, or be fully silent in history?
4. Should server-mode requests eventually adopt the same transactional turn model?

## Risks
- introducing inconsistent rollback between REPL and TUI
- breaking tool-call ordering invariants
- leaking phantom per-turn ledger entries after cancellation
- removing too much history in partial-commit cases
- racing between local cancellation and late provider completion

## Success criteria
- cancelled turns do not pollute context when no committed state exists
- provider 4xx/5xx failures do not leave stray user turns in history by default
- tool-call flows remain protocol-valid under interruption
- per-turn cost and round-trip ledgers remain synchronized with history mutations
- retrying after cancellation or provider failure does not duplicate stale context
