# PLAN_COMPACTION_FIX

## Completed Work
The following pieces of this fix have already been completed:
- richer `Message` and `ToolCall` data now exist in the shared model layer
- `ConversationBoundaryTracker` helper logic has been added to preserve safer history tails
- `HistoryService.append_message(...)` now exists to accept enriched messages
- supporting docs for this fix have already been created

## Goal
Finish the conversation compaction and tool-cluster preservation work so history compaction never orphans tool results and remains safe for plain chat, tool calls, REPL usage, and TUI usage.

The current implementation now has the right direction in place: `HistoryService` can store enriched messages, `ConversationBoundaryTracker` can preserve safer tails, and the model layer can represent tool metadata. The remaining work is to wire the structured completion path end-to-end so the application actually populates those fields during real turn execution.

## Current Direction
The next implementation pass should keep the architecture simple and explicit:
- `TurnCompletionResult` is the structured result for completed turns.
- `ConversationTurnResult` remains a thin REPL/UI convenience wrapper if needed.
- `LLMService.complete(...)` should eventually return structured data instead of only plain text.
- `ConversationSession` should append enriched `Message` instances through `HistoryService.append_message(...)`.
- `ConversationBoundaryTracker` should preserve complete conversation units, including tool-call clusters, when compaction trims history.
- Compaction remains separate from rate limiting; see `docs/cache/PLAN_RATE_LIMITING.md` for send-path throttling policy.

The primary goal is not to add more wrappers. The primary goal is to move structured turn information from the tool/LLM boundary into persistent history in one coherent path.

## Proposed Workflow
1. Execute a conversation turn through the LLM/tool path.
2. Produce a structured completion result that includes assistant text, response identifiers, and any enriched history messages.
3. Append the structured messages to history before the next compaction decision.
4. Let the boundary tracker preserve complete units when compaction triggers.
5. Compact only after the history already contains the right metadata.

## Required Data
The conversation layer should be able to represent:
- plain user turns
- plain assistant responses
- assistant tool-call messages
- tool result messages linked by `tool_call_id`
- response lineage metadata such as `response_id` and `parent_response_id`

The shared `Message` model already supports the required metadata fields, but the fields still need to be populated by the completion path.

## Verification Focus
Any implementation should be verified for:
- plain text conversations still work as before
- tool-call turns produce enriched history messages
- `HistoryService.append_message(...)` receives structured messages when available
- compaction preserves assistant/tool clusters intact
- no tool result is orphaned by the compaction tail selection
- REPL and TUI adapters stay thin and compatible
- existing non-tool history flows do not regress

## Notes
See `ROADMAP_COMPACTION_FIX.md` for the narrative overview of how this fix evolved.

- Prefer one canonical structured result for the LLM/tool path.
- Keep UI wrappers thin and avoid creating a second competing completion contract.
- Do not force compaction logic to infer metadata that should already be present in history.
- Add tests before broadening the LLM/session contract again.
