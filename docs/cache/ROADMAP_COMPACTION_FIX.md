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

## Phase 7: Recognize the remaining gap
The biggest remaining issue is not the compaction boundary itself. It is the lack of a fully wired structured completion path.

What still needs to happen:
- the LLM/tool path must emit structured completion data
- the session layer must append enriched messages into history
- tool metadata must be populated at the source of truth, not inferred later
- tests must validate that compaction preserves tool clusters end-to-end

## Current State
The foundation is now in place:
- richer models exist
- boundary tracking exists
- history can accept enriched messages
- docs explain the remaining work

What is not yet complete:
- the end-to-end structured completion flow that populates the metadata during real execution

## Next Roadmap Step
The next implementation milestone should focus on one thing only:
- make the LLM/tool completion path produce and persist enriched messages consistently

Once that is done, the compaction behavior can be verified against real tool-call histories rather than approximate raw-message tails.
