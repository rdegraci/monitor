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
- [x] Removed `compact_with_summary` alias on `HistoryService`; the canonical method is `compact(summary_text) -> None` (no boolean return).
- [x] Removed `RuntimeConfig.summarization` and `RuntimeConfig.compaction_config` property aliases; canonical name is `summarization_settings`.
- [x] Removed the dead `save_summary` getattr fallback from `_persist_compaction_summary`; narrowed catch from `Exception` to `OSError`.
- [x] Removed `compact_summary_filename` helper and its test (duplicated `CompactionStore._build_summary_path`).
- [x] Removed `HistoryService._recent_messages` (dead).
- [x] Imports and type hints rechecked after the refactor.

## Additional fixes that landed (post-original-checklist)
- [x] Compaction now runs *proactively* before the LLM call (was reactive, which couldn't prevent the current turn from failing).
- [x] Soft trigger added: `compaction_soft_ratio` (default 0.5) fires compaction at the 50% context-window mark, with the hard trigger as backstop.
- [x] Hard-coded `keep_turns = 2` replaced by `SummarizationSettings.preserve_units`.
- [x] Estimator bug fixed: `Message` dataclasses are now converted to `{role, content}` dicts before being passed to `ConfigService.estimate_token_usage`, which previously raised `AttributeError` inside a broad except and silently disabled the context-window trigger.
- [x] User-message duplication fixed: `LLMRequestBuilder.build_input(history)` no longer appends `user_input` separately on top of history. `LLMService.complete(history)` derives `input_text` from `history[-1]`.
- [x] Tool-call metadata (`tool_calls`, `tool_call_id`, `name`) preserved through `build_input` — the boundary tracker's cluster preservation now survives end-to-end.
- [x] Summarization output cap is enforced via `max_output_tokens` plumbed to the OpenAI Responses API (not a soft string hint).
- [x] `token_limit` clamped to `output_window` to prevent the provider from rejecting an over-cap request.
- [x] Summarization fallback (when the LLM call fails) carries forward the prior system summary with an end-truncation cap of `token_limit × 4` chars + a new placeholder line. Monotonic, bounded.
- [x] `CompactionStore` documented as forensic-only; filename adds seconds + `-N` collision counter; exclusive-create writes; 30-day retention sweep on save.
- [x] Compaction summaries directory derived correctly via `get_compaction_dir_path()`; wiring bug (`CompactionStore(config_service)`) is fixed.
- [x] Two divergent token estimators unified — `RequestCapacityService` and `RateLimitService` both delegate to `ConfigService.estimate_token_usage`.
- [x] All tests for compaction use only the public interface (no `_`-prefixed access).
