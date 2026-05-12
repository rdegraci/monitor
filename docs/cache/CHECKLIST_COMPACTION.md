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

## Milestone 1: Policy definition
- [x] Define `CONVERSATION_MAX_TURNS` as the conversation budget in turns.
- [x] Define compaction as a pre-limit operation rather than a hard-limit failure.
- [x] Define a hard-coded trigger threshold at roughly 10% remaining turns.
- [x] Define `summarization.maximum_summary_tokens` as the upper bound for a summary request.
- [x] Define `summarization.prompt.template` as the configurable summary prompt.
- [x] Define preservation of the most recent turns verbatim.
- [x] Define fallback behavior when summarization fails.

## Milestone 2: Runtime placement
- [x] Compaction lives in `ConversationSession`, with `HistoryService` handling the summarized-history replacement.
- [x] Define the boundary between turn tracking and history summarization.
- [x] Define how compacted summaries are reinserted into the active conversation state.
- [x] Define how compaction interacts with snapshot/state reporting.
- [x] Define the minimal summarizer service interface and where it is owned.

## Milestone 3: UI and telemetry
- [ ] Define how the status line should display turns remaining.
- [ ] Define whether the UI should surface compaction eligibility.
- [ ] Define whether the UI should indicate the most recent compaction event.
- [ ] Keep the status line compact and readable on narrow terminals.
- [ ] Avoid adding extra configuration knobs for status reporting unless needed.

## Milestone 4: Verification
- [x] Add tests for compaction threshold calculation.
- [x] Add tests for summary generation budgeting.
- [x] Add tests for preserving recent turns verbatim.
- [x] Add tests for compaction fallback behavior.
- [x] Add tests for headroom reporting after compaction.

## Notes
- Keep the first implementation small and deterministic.
- Avoid exposing too many tuning knobs before the behavior is stable.
- Prefer a clear compaction policy over a highly configurable one.
- Compaction should improve long-run usability without surprising the user.
