# ROADMAP_COMPACTION_FIX

## Purpose
This roadmap summarizes how the compaction and tool-cluster preservation work evolved, what has already been completed, and how the remaining work is expected to proceed.

It is intended as a narrative companion to:
- `docs/cache/PLAN_COMPACTION_FIX.md`
- `docs/cache/CHECKLIST_COMPACTION_FIX.md`
- `docs/cache/PLAN_COMPACTION.md`
- `docs/cache/PLAN_RATE_LIMITING.md`

## Phase 1: Identify the compaction gap
The original compaction implementation was good at triggering history reduction, but it was not yet safe for structured tool flows.

The main issues discovered were:
- compaction was only preserving a small raw tail of history
- tool-result messages could be separated from the assistant turn that caused them
- the history model did not carry enough metadata to reason about tool-call clusters precisely
- the completion path did not yet populate structured fields end-to-end

At this stage, compaction worked for basic chat, but it was not guaranteed to preserve tool-call integrity.

## Phase 2: Clarify the desired behavior
The design goal became explicit:
- compaction must never orphan a tool result
- the preserved history tail must keep complete conversation units intact
- plain text conversations must continue to work unchanged
- REPL and TUI usage should remain compatible
- compaction must stay separate from rate limiting

This led to the realization that compaction needed better boundaries, not just a different threshold.

## Phase 3: Add a richer data model
To support safe preservation, the shared model layer was extended.

Completed model work includes:
- adding `ToolCall`
- extending `Message` with optional tool and response metadata
- keeping the original `role` and `content` fields intact so existing callers still work

This gave the codebase a place to store structured tool information when it becomes available.

## Phase 4: Add boundary tracking
The next step was to teach compaction how to preserve coherent history units.

Completed work includes:
- adding `ConversationBoundaryTracker`
- using it to count user turns
- using it to preserve a safer tail during compaction
- making it aware of tool-call and tool-result linkage when metadata is present

This was the first major step toward preventing orphaned tool results during history trimming.

## Phase 5: Prepare history for enriched messages
The history layer was then prepared to accept richer entries.

Completed work includes:
- adding `HistoryService.append_message(...)`
- keeping `append(...)` as a compatibility path
- syncing the boundary tracker whenever history changes

This created an explicit place for future structured messages to enter persistent history.

## Phase 6: Document the fix
Once the architecture direction was clear, the work was documented so it could be tracked and finished deliberately.

Completed docs include:
- `PLAN_COMPACTION_FIX.md`
- `CHECKLIST_COMPACTION_FIX.md`

These documents capture both the completed groundwork and the remaining structured-completion wiring.

## Phase 7: Wire the structured completion path
The structured completion path is now wired through `LLMService.complete(...)` and `ConversationSession`.

What that unlocked:
- structured completion data now flows through the primary LLM completion entrypoint
- the session layer can persist enriched messages into history
- tool metadata is no longer blocked on initial wiring
- compaction can be validated against real structured turns instead of only approximate raw-message tails

## Current State
The compaction-fix work is complete. The subsystem now:
- Carries enriched `Message` + `ToolCall` data through the model layer.
- Preserves complete units (including assistant + tool-call clusters) via `ConversationBoundaryTracker`.
- Threads `tool_calls` / `tool_call_id` / `name` metadata through `LLMRequestBuilder` so the cluster survives end-to-end into the LLM request (the previous strip-at-request-layer bug is fixed).
- Compacts proactively (before the LLM call), not reactively.
- Triggers on soft context-window pressure (50% default), hard backstop, or turn-budget cliff.
- Enforces summary output via `max_output_tokens` (clamped to `output_window`) instead of a soft string hint.
- Falls back deterministically when the summarization LLM call fails, carrying forward the prior system summary with bounded growth.
- Persists summaries as forensic-only artifacts (race-safe filenames, 30-day retention sweep).
- Surfaces a yellow `compacting` status indicator mid-turn via the `RuntimeContext.status_listener` callback.

## Subsequent Work That Landed
After the original roadmap completed, additional issues were found and fixed:
- The token estimator in `ConfigAccessorService` was being called with `Message` dataclass instances where it expected `dict`s, raising `AttributeError` inside a broad `except` and silently disabling the context-window compaction trigger. Fix: convert messages to `{role, content}` dicts at the call site in `conversation_session._estimate_compaction_token_count`.
- User messages were being duplicated in every LLM request because `LLMRequestBuilder.build_input` appended `user_input` separately on top of a history that already contained it. Fix: `build_input(history)` renders from history alone; `LLMService.complete(history)` derives `input_text` from `history[-1]`.
- The compaction summary file path was wired with `CompactionStore(config_service)` where it should have been a `Path` — every persistence write silently failed, hidden by a broad `except` in `_persist_compaction_summary`. Fix: derive via `get_compaction_dir_path()`, narrow the catch to `OSError`.
- Three property aliases for the same settings object (`summarization`, `compaction_config`, `summarization_settings`) collapsed to a single canonical name.
- `compact_with_summary` (which always returned `True`) collapsed into `compact(...) -> None`.

## Status
This roadmap is closed. See `PLAN_COMPACTION.md` for the canonical description of the resulting subsystem and `CHECKLIST_COMPACTION_FIX.md` for the line-by-line list of what landed.
