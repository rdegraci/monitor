# CHECKLIST_COMPACTION_FIX

## Completed
- [x] Verify `Message` contains the metadata needed for tool preservation.
- [x] Verify `ToolCall` is available where tool calls are represented.
- [x] Verify `TurnCompletionResult` contains the fields needed by the TUI and history path.
- [x] Verify `ConversationBoundaryTracker` preserves complete units.
- [x] Verify `HistoryService.append_message(...)` accepts enriched `Message` objects.
- [x] Revisit docs and comments to match the final data flow.

## Notes
- See `ROADMAP_COMPACTION_FIX.md` for the narrative overview of how this work progressed.

## Planning
- [ ] Confirm the canonical structured turn result type for the LLM/tool path.
- [ ] Confirm whether `ConversationTurnResult` remains REPL-only or becomes a thin adapter.
- [ ] Confirm the final history append path for enriched `Message` objects.

## LLM / Tool Path
- [ ] Update `LLMService.complete(...)` to return a structured result.
- [ ] Ensure tool-call turns populate enriched assistant and tool messages.
- [ ] Ensure response lineage metadata is captured when available.
- [ ] Keep plain text turns working.

## Session / History Path
- [ ] Update `ConversationSession` to consume the structured result.
- [ ] Preserve REPL compatibility.
- [ ] Preserve TUI compatibility.

## Compaction Behavior
- [ ] Verify tool-call clusters remain attached to their assistant turn.
- [ ] Verify tool results are never orphaned after compaction.
- [ ] Verify plain assistant/user turns still compact correctly.

## Tests
- [ ] Add test for plain assistant completion.
- [ ] Add test for tool-call completion history enrichment.
- [ ] Add test for compaction preserving assistant/tool clusters.
- [ ] Add test for backward compatibility with plain `Message(role, content)` usage.

## Cleanup
- [ ] Remove any temporary bridges or duplicate result types if they become redundant.
- [ ] Re-check imports and type hints after the refactor is complete.
