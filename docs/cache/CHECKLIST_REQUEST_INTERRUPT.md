# CHECKLIST_REQUEST_INTERRUPT

Legend:
- [x] done
- [~] partial
- [ ] not started

## History integrity
- [x] Confirm where the user turn first becomes durable in history.
  - `src/monitor/core/conversation.py` → `prepare_query_context()`
  - `src/monitor/lib/history.py` → user message append path in `append_to_history_with_count()`
- [x] Confirm where per-turn cost bucket creation occurs.
  - `src/monitor/lib/history.py` opens a `TURN_COSTS_USD` bucket when a user message lands.
- [x] Confirm where round-trip ledger creation occurs.
  - `src/monitor/lib/history.py` opens a parallel `TURN_ROUND_TRIPS` bucket when a user message lands.
- [~] Identify all generic LLM failure exits that currently leave the user turn in history.
  - `conversation.query()` now rolls back tracked uncommitted turns for generic initial failures, malformed initial responses with no choices, and cancellation-style initial errors.
  - A full inventory across all provider/adaptor/tool-follow-up paths is still incomplete.
- [x] Identify all structured refusal exits that already remove the user turn.
  - `src/monitor/lib/llm_utils.py` handles `refusal`, `content_filter`, and `safety`.

## Interrupt sources
- [~] Review prompt-edit cancellation before submit.
  - Input collection paths catch `KeyboardInterrupt` and generally return without submitting.
  - Request-interrupt-specific history tests are still missing.
- [~] Review Ctrl-C cancellation after submit.
  - Cancellable request paths exist in `src/monitor/core/llm.py` and `src/monitor/core/llm_responses_adapter.py`.
  - TUI parity test now verifies mid-turn Ctrl-C does not quit or corrupt state.
  - End-to-end rollback verification for actual injected post-submit Ctrl-C is still missing.
- [ ] Review Esc-based cancellation semantics in TUI or prompt flows.
- [ ] Review cancellation behavior during tool execution.
- [~] Review cancellation behavior during multi-step tool-call follow-up requests.
  - Tool-call protocol integrity logic exists.
  - Regression coverage now proves partial protocol state is preserved when follow-up LLM processing fails after assistant/tool messages were committed.
  - Dedicated interruption-specific verification is still missing.

## Provider failure classes
- [~] Review HTTP 400 handling before any valid response object exists.
  - Generic early-failure rollback exists, and malformed no-choice initial responses now roll back.
  - No targeted 400-path verification was found.
- [~] Review HTTP 401 handling.
  - Mocked initial provider-auth failure now verifies rollback of tracked uncommitted turn.
- [x] Review HTTP 403 handling.
  - Mocked initial-completion error test verifies rollback.
- [~] Review HTTP 429 handling.
  - Mocked initial rate-limit failure now verifies rollback of tracked uncommitted turn.
- [~] Review HTTP 5xx handling.
  - Mocked initial server-error failure now verifies rollback of tracked uncommitted turn.
  - Follow-up tool-call failure test verifies partial protocol state is preserved rather than naively popped.
- [~] Review timeout and network exception handling.
  - Timeout/network-style initial failures now have mocked rollback coverage.
  - Broader end-to-end adapter-path verification is still incomplete.

## Partial commit / protocol integrity
- [~] Verify assistant tool-call messages are never left orphaned.
  - Tool-order validation and orphan-prevention logic exist.
  - Follow-up failure regression test now proves committed assistant tool-call state is preserved in history.
  - Interruption-specific verification is still incomplete.
- [~] Verify tool-result pairing is preserved under failures.
  - Pairing/orphan-prevention logic exists.
  - Follow-up failure regression test now proves assistant/tool result pairing survives a post-tool follow-up error.
- [x] Verify partial tool-call turns are not naively popped.
  - Rollback is now stateful and no longer relies on naive tail-user popping alone.
  - Regression coverage now proves a follow-up failure after committed assistant/tool protocol state does not pop the partial turn.
- [~] Verify interrupted turns keep minimal coherent protocol state.
  - Follow-up failure coverage now demonstrates minimal coherent assistant/tool protocol state is preserved after partial commit.
  - True interruption/cancellation-specific coverage is still missing.
- [ ] Verify side-effecting tool interruptions are handled conservatively.

## Accounting integrity
- [x] Verify rollback also removes matching TURN_COSTS_USD bucket.
  - Covered in `src/monitor/core/conversation.py`, `src/monitor/lib/llm_utils.py`, and regression tests.
- [x] Verify rollback also removes matching TURN_ROUND_TRIPS bucket if appropriate.
  - Covered in the same code paths and strengthened refusal tests.
- [~] Verify cancellation estimate accounting does not create permanent phantom turn state.
  - Conservative cancellation accounting exists, but full reconciliation verification is still missing.
- [~] Verify retry after failure does not duplicate prior failed-turn accounting.
  - Rollback reduces stale-context risk, but explicit retry regression tests are still missing.

## Front-end parity
- [~] Ensure REPL and TUI follow the same turn-state policy.
  - Both front-ends now have evidence for conservative mid-turn Ctrl-C handling and uncommitted-turn rollback on initial generic failure paths.
  - Full parity audit is still incomplete.
- [~] Ensure interrupt UX is understandable and consistent.
  - Friendly interrupt handling exists in multiple paths, and TUI mid-turn Ctrl-C behavior is now explicitly tested.
  - Parity and consistency are not fully audited.
- [~] Ensure cancellation before submit is a no-op history-wise.
  - Likely true from input flow, but not directly verified with request-interrupt tests.
- [~] Ensure cancellation after submit but before commit rolls back the turn.
  - Generic initial failure/cancellation rollback exists and now has broader mocked coverage.
  - True post-submit interrupt injection is not fully verified.

## Verification
- [~] Add tests for pre-submit Esc/Ctrl-C behavior.
  - Ctrl-C tests exist in input-mode handling, but not fully at request-interrupt history level; Esc coverage missing.
- [~] Add tests for post-submit Ctrl-C rollback behavior.
  - Cancellation-style initial failure is now covered in `conversation.query()` tests.
  - True end-to-end signal-driven post-submit Ctrl-C rollback is still missing.
- [x] Add tests for generic 4xx rollback behavior when uncommitted.
  - Mocked `HTTP 401`, `HTTP 403`, and `HTTP 429` initial failures now verify rollback.
- [~] Add tests for 5xx rollback behavior when uncommitted.
  - Mocked `HTTP 500` initial failure verifies rollback.
  - Broader provider/adaptor coverage still missing.
- [~] Add tests for timeout/network rollback behavior.
  - Mocked timeout/network initial failures now verify rollback.
  - End-to-end adapter-level verification still missing.
- [~] Add tests for partial tool-call interruption preserving coherent state.
  - Follow-up failure regression test now verifies coherent partial assistant/tool protocol state is preserved after partial commit.
  - True interruption/cancellation-specific coverage is still missing.
- [ ] Add tests for race between cancellation request and late provider response.
