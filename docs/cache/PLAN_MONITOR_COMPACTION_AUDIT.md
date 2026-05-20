# PLAN_MONITOR_COMPACTION_AUDIT

## Scope
This document tracks the audit and hardening of the compaction subsystem in the **original `src/monitor/`** codebase (the procedural module that predates the OOP rewrite under `src/monitor_oop/`).

It is separate from `PLAN_COMPACTION_FIX.md` / `CHECKLIST_COMPACTION_FIX.md`, which document the structured-message + tool-cluster preservation work in `src/monitor_oop/`. Those docs are closed; this one is open.

## Motivation
The user repeatedly hit HTTP 400 "context length exceeded" responses from the LLM provider that left the session unrecoverable except via `:reset_history`. Tracing those failures into the compaction subsystem surfaced multiple independent bugs in `src/monitor/lib/history.py`, plus several lower-priority issues nearby.

## Key Files
- `src/monitor/lib/history.py` — entry points for `check_limits`, `append_conversation_history`, `generate_conversation_summary`, `reset_conversation_with_summary`
- `src/monitor/lib/redis_utils.py` — caller of `append_to_history_with_count`
- `src/monitor/lib/built_in_commands.py` — caller of `adjust_history_size`
- `tests/monitor/lib/test_history_summarization.py` — public-API regression suite

## What Has Landed

### Pre-summary destructive truncation (removed)
`append_conversation_history` previously truncated `conversation_history` in place *before* invoking the summarizer. A failure mid-summary left the conversation permanently shortened with no summary message. Replaced with a two-stage attempt: render full history first, fall back to a truncated *copy* if the LLM rejects, and only commit on success.

### `generate_conversation_summary` cap-drop bug (fixed)
The summary call passed only `max_completion_tokens`, which providers using `drop_params=True` silently strip, producing unbounded summary output that re-overflowed the context window. Now passes `max_tokens` alongside `max_completion_tokens` and validates the returned summary length post-call.

### `reset_conversation_with_summary` overflow (fixed)
Previously committed a new history without verifying the resulting state fit `MAX_TOKEN_COUNT`. Reset paths could produce a state that immediately overflowed on the next request. Replaced with atomic build-then-swap and an auto-truncate fallback via `_truncate_summary_to_fit` and `_build_truncated_history_copy`.

### `check_limits` over-eager triggers (fixed) — Audit Item #1
Secondary triggers (`conversation_size`, `time_limit_seconds`, `memory_pressure`) used to fire summarization independently of token-budget state. With `MAX_TOKEN_COUNT` set high relative to message count, this caused expensive compactions that produced no benefit and confused downstream state. Gated behind `SECONDARY_PRESSURE_RATIO = 0.5`:

```python
should_summarize = over_token_limit or (under_secondary_pressure and secondary_trigger)
```

(`src/monitor/lib/history.py:812-828`)

### `skip_summary` token-budget gap (fixed) — Audit Item #2
When the Responses-API + reasoning-model + `response_id` triple held, summarization was skipped and history was truncated to `system + last 20 non-system messages` — without checking `MAX_TOKEN_COUNT`. Large recent messages could still overflow. Replaced with pre-validation: build the proposed history, count tokens, drop additional oldest non-system messages until it fits, and bail without mutating state if even the system prompt alone overflows.

(`src/monitor/lib/history.py:264-345`)

### Circular-import partial fix
`monitor.lib.redis_utils` and `monitor.lib.built_in_commands` had module-level imports of `monitor.lib.history` that produced circular-import errors when history tests ran standalone. Deferred to function-local imports. A third cycle through `monitor.lib.llm_utils` remains (reverted after it broke `test_llm.py`); history tests now collect in full-suite mode but not in isolation.

## Remaining Work

### M1 — Tool-call orphaning risk in `skip_summary` truncation
The "system + last N non-system messages" cut (and now the additional trim-to-fit step) can split a `tool_call` from its `tool_result`, leaving an orphan message that some providers reject. The summarize path has cluster preservation; the skip path does not. Should walk back from the cut boundary until the kept prefix begins outside a tool cluster.

### M2 — Stale rolling-window rate-limit counters after compaction
Chain-aware token caches do not decrement when history shrinks via compaction. The rate-limiter can therefore deny requests based on token estimates that no longer match reality. Sits between the compaction and rate-limiting subsystems; needs a cache invalidation hook on every committed compaction.

### L1 — `prompt_count_since_summarization` reset scatter
Multiple call sites reset this counter (post-summary, post-reset, post-skip-truncation). High risk of divergence over time. Should be centralized to a single helper that is the only writer.

### L2 — Remaining circular import via `llm_utils`
History tests cannot run in isolation because `monitor.lib.llm_utils` imports `history` at module scope, and `llm_utils` ↔ `llm_responses_adapter` is itself a cycle via `config.py`. The full-suite path papers over it. Long-term: lift shared types into a leaf module.

### L3 — Broad `except Exception` swallowing
Several compaction-adjacent paths catch `Exception` and only `logger.error(...)` without re-raising or surfacing a typed result. Hides bugs like the cap-drop above. Narrow to specific exception classes per call site.

## Verification
Full `tests/monitor` suite: 510 passed, 1 skipped, 4 subtests passed after both Item #1 and Item #2 landed. New regression cases added under `tests/monitor/lib/test_history_summarization.py`:
- `_fill_to_conversation_size_no_token_pressure` — secondary trigger without token pressure does not summarize
- `_simulate_time_trigger_no_token_pressure` — same, for time trigger

Tests exercise only the public interface (`check_limits`, `append_conversation_history`, `reset_conversation_with_summary`). No `_`-prefixed access.

## Notes
- Public-API-only constraint for tests is non-negotiable: tests that need a public API to be added in order to pass should not exist.
- Items M1 and M2 each carry a fresh class of HTTP 400 risk; L items are correctness/maintenance hygiene.
