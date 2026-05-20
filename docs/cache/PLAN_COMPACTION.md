# PLAN_COMPACTION

## Goal
Define how `monitor_oop` compacts long-running conversations before context-window pressure becomes a real failure.

Compaction keeps the session usable over many turns by inserting a summary of older history when the conversation grows large. It runs *proactively* — before the LLM call that would otherwise fail — and uses a soft trigger (default 50% of context window) with a hard backstop and a turn-budget cliff as final safety.

Compaction is a capacity-management concern and stays separate from rate limiting (see `docs/cache/PLAN_RATE_LIMITING.md`).

## Current Direction
The compaction model is small and opinionated:
- `SummarizationSettings.compaction_soft_ratio: float = 0.5` is the soft context-window trigger as a fraction of the window. Setting outside `(0, 1)` disables the soft trigger.
- The hard context-window trigger fires when `estimated_token_count + output_window >= context_window`.
- `RuntimeConfig.conversation_turn_budget` defines a backstop turn cliff; compaction fires when remaining turns fall below `0.1 × max_turns`. This is unreachable in practice once the context-window triggers work (since the token estimator now functions correctly).
- `SummarizationSettings.token_limit: int = 4000` bounds the summary output via `max_output_tokens` on the LLM call (enforced, not a soft string hint).
- `SummarizationSettings.prompt_template` controls the summary prompt (only `{message_count}` is interpolated; the previous `{messages}` placeholder was removed because it doubled the history when used in a custom template alongside the request body).
- `SummarizationSettings.preserve_units: int = 2` controls how many conversational units the boundary tracker preserves at the tail during compaction.
- `ConversationSession._maybe_compact_history` runs *before* the LLM call: it appends the user message, evaluates compaction, runs it if needed, then dispatches the LLM call. On compaction it emits `"compacting"` via `RuntimeContext.emit_status`, runs summarization + replacement, then restores `"working"` in a `try/finally`.
- `HistoryService.should_compact(context_window, estimated_token_count, output_window)` evaluates the three triggers in order.
- `HistoryService.compact(summary_text)` performs the replacement: clear history, append the system summary, append the boundary-aware preserved tail, sync trackers, persist the summary best-effort via `CompactionStore` (forensic-only — never read back; 30-day retention sweep on every save).
- `SummarizationService.summarize` makes the LLM call with `max_output_tokens=min(token_limit, output_window)` and falls back to a deterministic summary on LLM failure or empty response. The fallback **carries forward** the prior system summary (capped at `token_limit × 4` chars, truncating accumulated placeholder lines first) plus a new placeholder line. Monotonic across repeated failures, bounded against unbounded growth.

The flow favors a clear, deterministic workflow over a highly configurable policy surface.

## Workflow
1. User submits input → session appends user message to history.
2. `_maybe_compact_history` runs:
   - Estimate token usage by converting `Message` dataclasses to request-shaped dicts and calling `ConfigService.estimate_token_usage` (the canonical estimator used by both compaction and rate-limit preflights).
   - Evaluate `should_compact`: soft trigger → hard backstop → turn-budget cliff.
   - If compaction fires: emit `"compacting"`, call `SummarizationService.summarize`, call `HistoryService.compact(summary)`, emit `"working"` via `finally`.
3. Dispatch the LLM call with the (possibly compacted) history.
4. Append the assistant response to history.

## Config Surface
The minimal config knobs are:
- `RuntimeConfig.context_window` — model context window (tokens).
- `RuntimeConfig.output_window` — model output window (tokens); reserved for headroom in the hard backstop.
- `RuntimeConfig.conversation_turn_budget` — turn-budget cliff.
- `summarization_settings.token_limit` — output cap for the summary call (clamped to `output_window`).
- `summarization_settings.prompt_template` — summary prompt template (`{message_count}` only).
- `summarization_settings.preserve_units` — preserved tail size.
- `summarization_settings.compaction_soft_ratio` — soft trigger as a fraction of `context_window`.

The canonical name on `RuntimeConfig` is `summarization_settings`. Legacy property aliases (`summarization`, `compaction_config`) have been removed.

## Policy Choices to Keep Internal for Now
The following behaviors should be internal implementation details unless the design changes later:
- exact compaction trigger ratio
- compaction hysteresis
- number of recent turns preserved verbatim
- fallback behavior if summarization fails
- exact formula for any remaining-turns indicator shown in the UI
- whether compaction may repeat in multiple passes

## UI Considerations
The TUI status line surfaces a `"compacting"` indicator (yellow) when compaction is in flight, transitioning back to `"working"` (yellow) when the summarization completes and the main LLM call begins. End-of-turn states are `"completed (idle)"` (green), `"failed (idle)"` (red), or `"rate limited (idle)"` (yellow) for transient rate-limit denials.

The status indicator update bypasses the event queue and uses direct attribute mutation + `application.invalidate()`, because the event queue doesn't drain mid-turn. The status listener registered on `RuntimeContext` is the bridge.

## Verification Focus
Any implementation should be verified for:
- compaction triggers before the hard limit is reached
- `ConversationSession` invokes compaction deterministically using the configured prompt template
- `HistoryService` preserves the newest turns during compaction
- summary generation stays bounded by `summarization.maximum_summary_tokens`
- stable turn continuity after compaction
- graceful fallback if summarization fails

## Notes
- The compaction implementation should live in the conversation/history layer, not in the TUI.
- Keep the first version deterministic and easy to test.
- Prefer clear behavior over many tunable knobs.
- The summary prompt should be concise but preserve the important context, constraints, and decisions from the conversation.
