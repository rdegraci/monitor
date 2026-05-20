# CHECKLIST_COMPACTION

## Goal
Track the work needed to add conversation compaction to `monitor_oop`.

Compaction should summarize older conversation history before the hard turn budget is exhausted, preserving enough recent context to keep the session coherent.

## Scope
This tracker covers:
- compaction policy and trigger threshold
- summarized-history replacement behavior
- summary prompt configuration
- summary token budgeting
- remaining-turns / headroom reporting in the UI
- verification of fallback behavior
- shaping the summarizer service interface
- compaction config staying separate from `src/monitor_oop/model_config_v2.json`
- compaction not being part of model rate-limit resolution
- rate limiting tracked separately in `docs/cache/CHECKLIST_RATELIMITING.md` and not conflated with compaction behavior
- compaction triggered by context-window pressure / capacity management
- compaction remaining separate from rate limiting
- compaction cooperating with request fit checks and headroom planning

## Milestone 1: Policy definition
- [x] Define `RuntimeConfig.conversation_turn_budget` as the conversation budget in turns (backstop trigger).
- [x] Define compaction as a pre-limit operation rather than a hard-limit failure.
- [x] Trigger thresholds: soft context-window (`compaction_soft_ratio = 0.5` of context window, default), hard context-window (input + reserved output ≥ window), turn-budget cliff at ~10% remaining (backstop).
- [x] Define `summarization_settings.token_limit` as the upper bound for a summary request (enforced via `max_output_tokens`, clamped to `output_window`).
- [x] Define `summarization_settings.prompt_template` as the configurable summary prompt.
- [x] Define `summarization_settings.preserve_units` as the number of tail units preserved by `ConversationBoundaryTracker`.
- [x] Compaction runs *proactively* (before the LLM call), not reactively.
- [x] Define fallback behavior when summarization fails: deterministic placeholder that carries forward the prior system summary (capped at `token_limit × 4` chars).
- [x] Define compaction as a response to context-window pressure and capacity management.
- [x] Define compaction as separate from rate limiting.
- [x] Define compaction as cooperating with request fit checks and headroom planning.

## Milestone 2: Runtime placement
- [x] Compaction lives in `ConversationSession`, with `HistoryService` handling the summarized-history replacement and cooperating with request-capacity checks before rate limiting.
- [x] Define the boundary between turn tracking and history summarization.
- [x] Define how compacted summaries are reinserted into the active conversation state.
- [x] Define how compaction interacts with snapshot/state reporting.
- [x] Define the minimal summarizer service interface and where it is owned.

## Milestone 3: UI and telemetry
- [x] TUI status indicator surfaces `compacting` (yellow) mid-turn during summarization. Transitions back to `working` (yellow) for the main LLM call.
- [x] Status indicator wiring uses `RuntimeContext.status_listener` callback set by `TuiApp` on construction. The listener bypasses the event queue (direct mutation + `application.invalidate()`).
- [ ] Define whether the UI should display turns remaining or context-window utilization as a quantitative indicator. (Deferred — the current state-based indicator covers the common case.)
- [ ] Define whether the UI should indicate the most recent compaction event in the transcript (currently silent — compaction is invisible apart from the brief `compacting` status flash). (Deferred.)

## Milestone 4: Verification
- [x] Add tests for compaction threshold calculation.
- [x] Add tests for summary generation budgeting.
- [x] Add tests for preserving recent turns verbatim.
- [x] Add tests for compaction fallback behavior.
- [x] Add tests for headroom reporting after compaction.
- [x] Add tests confirming compaction is triggered by context-window pressure and capacity management.
- [x] Add tests confirming compaction remains separate from rate limiting.
- [x] Add tests confirming compaction cooperates with request fit checks and headroom planning.

## Notes
- Keep the first implementation small and deterministic.
- Avoid exposing too many tuning knobs before the behavior is stable.
- Prefer a clear compaction policy over a highly configurable one.
- Compaction should improve long-run usability without surprising the user.
