# ROADMAP_REQUEST_INTERRUPT

## Objective
Improve Monitor turn lifecycle handling so interruptions and provider failures do not pollute context history, while preserving protocol correctness for partial tool-call flows.

## Phase 1: document current behavior
- Trace the current turn lifecycle from submit to history mutation.
- Catalog generic failure paths, refusal paths, and cancellation paths.
- Document where current behavior already preserves invariants well.
- Document where failed/cancelled user turns remain in history.

## Phase 2: define turn-state model
- Establish the conceptual states: pre-submit, submitted/uncommitted, partially committed, committed, interrupted.
- Define which failure/interrupt classes cause rollback.
- Define which partial-commit states require repair instead of rollback.
- Align REPL and TUI on the same semantics.

## Phase 3: harden generic failure handling
- Normalize handling for provider 4xx/5xx failures.
- Normalize handling for timeout/network failures.
- Ensure rollback is applied only when no committed assistant/protocol state exists.
- Keep ledgers synchronized with any rollback.

## Phase 4: harden user interruption handling
- Clarify prompt-edit cancel behavior before submit.
- Clarify in-flight Ctrl-C behavior after submit.
- Clarify Esc behavior when used as turn cancellation.
- Handle interruption races against late provider completion.

## Phase 5: preserve tool-call integrity
- Reuse the existing orphan-prevention philosophy.
- Ensure partial tool-call turns remain coherent under interruption.
- Avoid naive pop-last-message behavior once tool protocol state has been committed.
- Preserve minimal interrupted state when necessary.

## Phase 6: verification and UX polish
- Add targeted tests for each failure/interrupt class.
- Validate REPL and TUI parity.
- Confirm retries after interruption or provider failure do not duplicate stale context.
- Reassess whether future server-mode request cancellation should adopt the same model.

## Exit condition
Monitor history should cleanly distinguish:
- turns that never really happened
- turns that were semantically refused
- turns that partially committed tool protocol state
- turns that completed normally
