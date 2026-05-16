# CHECKLIST_COMPACTION_FIX

## Completed
- [x] Verify `Message` contains the metadata needed for tool preservation.
- [x] Verify `ToolCall` is available where tool calls are represented.
- [x] Verify `TurnCompletionResult` contains the fields needed by the TUI and history path.
- [x] Verify `ConversationBoundaryTracker` preserves complete units.
- [x] Verify `HistoryService.append_message(...)` accepts enriched `Message` objects.
- [x] Revisit docs and comments to match the final data flow.
- [x] Confirm the canonical structured turn result type for the LLM/tool path.
- [x] Update `LLMService.complete(...)` to return a structured result.
- [x] Update `ConversationSession` to consume the structured result.
- [x] Validate the exact tool-call history shape emitted by structured completions.
- [x] Ensure response lineage metadata is captured when available.
- [x] Verify response lineage is retained through history writes and reloads.
- [x] Verify tool-call clusters remain attached to their assistant turn in history.
- [x] Verify tool results are never orphaned after compaction.
- [x] Verify plain assistant/user turns still compact correctly.

## Notes
- See `ROADMAP_COMPACTION_FIX.md` for the narrative overview of how this work progressed.

## Planning
- [x] Confirm whether `ConversationTurnResult` is now best treated as a thin REPL/UI adapter.
- [x] Confirm the final history append path for enriched `Message` objects.

## LLM / Tool Path
- [x] Structured completion wiring is complete for tool-call and plain-text turns.
- [x] Keep plain text turns working.

## Session / History Path
- [x] Preserve REPL compatibility.
- [x] Preserve TUI compatibility.

## Compaction Behavior
- [x] Verify tool-call clusters remain attached to their assistant turn in history.
- [x] Verify tool results are never orphaned after compaction.
- [x] Verify plain assistant/user turns still compact correctly.
- [x] Verify plain `Message(role, content)` compaction remains covered by the new plain-message compaction test.

## Tests
- [x] Add test for plain assistant completion.
- [x] Add test for tool-call completion history enrichment and validate the structured history shape for tool-call turns.
- [x] Add test for assistant turn history with response lineage metadata.
- [x] Add test for compaction preserving assistant/tool clusters in history.
- [x] Add test covering plain `Message(role, content)` compaction behavior.

## Cleanup
- [ ] Remove any temporary bridges or duplicate result types if they become redundant.
- [ ] Re-check imports and type hints after the refactor is complete.
