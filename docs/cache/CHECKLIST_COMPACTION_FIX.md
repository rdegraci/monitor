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

## Notes
- See `ROADMAP_COMPACTION_FIX.md` for the narrative overview of how this work progressed.

## Planning
- [ ] Confirm whether `ConversationTurnResult` remains REPL-only or becomes a thin adapter.
- [ ] Confirm the final history append path for enriched `Message` objects.

## LLM / Tool Path
- [x] Structured completion wiring is complete for tool-call and plain-text turns.
- [ ] Validate the exact tool-call history shape emitted by structured completions.
- [ ] Ensure response lineage metadata is captured when available.
- [ ] Keep plain text turns working.

## Session / History Path
- [x] Preserve REPL compatibility.
- [x] Preserve TUI compatibility.
- [ ] Verify response lineage is retained through history writes and reloads.

## Compaction Behavior
- [ ] Verify tool-call clusters remain attached to their assistant turn in history.
- [ ] Verify tool results are never orphaned after compaction.
- [ ] Verify plain assistant/user turns still compact correctly.

## Tests
- [ ] Add test for plain assistant completion.
- [ ] Add test for tool-call completion history enrichment and validate the structured history shape for tool-call turns.
- [ ] Add test for assistant turn history with response lineage metadata.
- [ ] Add test for compaction preserving assistant/tool clusters in history.
- [ ] Add test for backward compatibility with plain `Message(role, content)` usage.

## Cleanup
- [ ] Remove any temporary bridges or duplicate result types if they become redundant.
- [ ] Re-check imports and type hints after the refactor is complete.
