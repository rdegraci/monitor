# PLAN_COMPACTION

## Goal
Define how `monitor_oop` should compact long-running conversations before the conversation budget is exhausted.

Compaction should keep the session usable over many turns without waiting for the hard limit to be hit. The current implementation triggers compaction deterministically inside `ConversationSession` when remaining turns fall at or below 10% of the configured budget, then uses `HistoryService` to preserve the newest turns verbatim while `SummarizationService` generates an LLM-backed summary through the request builder, response client, and adapter flow.

Compaction is a capacity-management response to context-window pressure, and it remains separate from rate limiting while still cooperating with request fit checks and headroom planning. Compaction is already implemented in the conversation/history layer and continues to work alongside request-capacity planning and telemetry.

## Current Direction
The compaction model stays intentionally small and opinionated:
- `CONVERSATION_MAX_TURNS` defines the hard conversation budget in turns.
- `summarization.maximum_summary_tokens` bounds the summary generation request.
- `summarization.prompt_template` controls how the summary is written.
- `ConversationSession` owns the deterministic compaction trigger flow.
- `HistoryService` owns turn tracking and replacement while keeping the newest turns intact.
- `SummarizationService` performs LLM-backed summary generation through the current request builder/response client/adapter flow.
- Compaction and rate limiting are separate concerns; see `docs/cache/PLAN_RATE_LIMITING.md` for send-path throttling policy.
- Compaction config remains separate from the greenfield model/rate-limit config schema, and model resolution lives in `model_config_v2.json`.

The current implementation favors a clear, deterministic workflow over a highly configurable policy surface.

## Proposed Workflow
1. Track the number of turns used and the number of turns remaining.
2. When remaining turns reaches the compaction threshold, mark the session as eligible for compaction.
3. Select the older conversation history that should be summarized.
4. Preserve the most recent turns verbatim so the conversation stays locally coherent.
5. Generate a summary using the configured prompt template.
6. Bound summary generation by `summarization.maximum_summary_tokens`.
7. Replace the compacted history with the summary plus the preserved recent turns.
8. Resume normal conversation flow with updated headroom.

## Config Surface
The intended minimal config knobs are:
- `CONVERSATION_MAX_TURNS`
- `summarization.maximum_summary_tokens`
- `summarization.prompt_template`

The current code keeps the surface small while leaving the summarization flow aligned with the existing request builder, response client, and adapter path.

## Policy Choices to Keep Internal for Now
The following behaviors should be internal implementation details unless the design changes later:
- exact compaction trigger ratio
- compaction hysteresis
- number of recent turns preserved verbatim
- fallback behavior if summarization fails
- exact formula for any remaining-turns indicator shown in the UI
- whether compaction may repeat in multiple passes

## UI Considerations
The TUI status line should be able to reflect turn headroom, including a remaining-turns style indicator. If compaction is active, the status line can surface the relevant headroom information without exposing the underlying policy mechanics.

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
