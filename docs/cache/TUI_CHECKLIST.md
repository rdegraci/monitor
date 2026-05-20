# TUI_CHECKLIST

## Goal
Track the work needed to keep the monitor_oop TUI aligned with the current implementation:
- Output
- Status Line
- Input

The TUI should remain responsive while background activity, including subagent execution, is in progress.
The TUI should consume TurnCoordinator snapshots rather than direct rendering callbacks.

## Scope
This tracker covers:
- the TUI presentation layer
- event-driven UI updates
- background completion handling
- integration with the current OOP runtime
- compatibility with the future subagent workflow
- TurnCoordinator as the per-turn coordination boundary
- the TurnCoordinator snapshot interface
- the transcript viewport architecture

## Milestone 1: Architecture and placement
- [x] Choose `src/monitor_oop/core/presentation/` as the home for TUI code.
- [x] Confirm the TUI does not belong under `core/application/`.
- [x] Define the initial TUI files:
  - `__init__.py`
  - `tui.py`
  - `layout.py`
  - `events.py`
- [x] Keep the TUI in the `monitor_oop` package rather than at the package root.
- [x] Keep presentation concerns separate from application and infrastructure concerns.
- [x] Define the minimal `TuiApp` field set.
- [x] Add `runtime_context` as a required `TuiApp` field.
- [x] Add `turn_coordinator` as a required `TuiApp` field.
- [x] Add `layout` as a required `TuiApp` field.
- [x] Add `event_queue` as a required `TuiApp` field.
- [x] Add `is_running` as a required `TuiApp` field.
- [x] Add `status_text` as an optional later `TuiApp` field.
- [x] Add `input_draft` as an optional later `TuiApp` field.
- [x] Add `active_task_id` as an optional later `TuiApp` field.
- [x] Wire the TUI around a `prompt_toolkit` `Application`.
- [x] Delegate `run_tui` to the `Application`-backed TUI entrypoint.
- [x] Use widget-backed output, status, and input handling.
- [x] Quiet TUI bootstrap in `build_app`.
- [x] Suppress runtime TUI logging during interactive execution.

## Milestone 2: UI contract
- [x] Define the Output pane responsibilities.
- [x] Define the Status Line responsibilities.
- [x] Define the Input pane responsibilities.
- [x] Define how background events update the UI.
- [x] Define how subagent results are surfaced in the UI.
- [x] Define how the UI keeps the current user draft responsive.
- [x] Define how `OutputEvent` is rendered into the Output pane.
- [x] Define how `StatusEvent` is rendered into the Status Line.
- [x] Define how `BackgroundCompletionEvent` updates the UI when background work finishes.
- [x] Define how `SubagentResultEvent` is injected as explicit internal context.
- [x] Define how `ErrorEvent` is surfaced without blocking the main chat loop.
- [x] Define how optional `InputDraftEvent` keeps the current draft responsive.
- [x] Define how TurnCoordinator owns internal context.
- [x] Define how TurnCoordinator owns subagent results.
- [x] Define how TurnCoordinator owns background completion state.
- [x] Define how TurnCoordinator owns request assembly input.
- [x] Define the structured internal-context record shape.
- [x] Define the `id` field for internal-context records.
- [x] Define the `source` field for internal-context records.
- [x] Define the `kind` field for internal-context records.
- [x] Define the `text` field for internal-context records.
- [x] Define the `timestamp` field for internal-context records.
- [x] Define optional `metadata` for internal-context records.
- [x] Distinguish mostly-internal raw records from UI-visible summaries.
- [x] Define how the TUI consumes TurnCoordinator snapshots instead of direct rendering callbacks.
- [x] Define `begin_turn` on TurnCoordinator.
- [x] Define `begin_turn` assigning a new turn id.
- [x] Define `begin_turn` clearing stale turn-scoped data.
- [x] Define `add_internal_context` on TurnCoordinator.
- [x] Define `add_internal_context` appending structured records in order.
- [x] Define `add_subagent_result` on TurnCoordinator.
- [x] Define `add_subagent_result` as a thin semantic wrapper that also stores a generic internal-context record.
- [x] Define `add_background_event` on TurnCoordinator.
- [x] Define `add_background_event` as append-only.
- [x] Define `mark_background_complete` on TurnCoordinator.
- [x] Define `mark_background_complete` recording completion.
- [x] Define `mark_background_complete` updating pending-work state.
- [x] Define `mark_background_complete` updating background status.
- [x] Define `snapshot` on TurnCoordinator.
- [x] Define `snapshot` returning a read-only view.
- [x] Define `clear_turn` on TurnCoordinator.
- [x] Define `clear_turn` as a strict reset of turn-local state.
- [x] Define `clear_turn` removing turn-scoped data.
- [x] Define the `turn_id` field in TurnCoordinator snapshots.
- [x] Define the `background_status` field in TurnCoordinator snapshots.
- [x] Define the `has_pending_work` field in TurnCoordinator snapshots.
- [x] Define the `internal_context_entries` field in TurnCoordinator snapshots.
- [x] Define the `subagent_results` field in TurnCoordinator snapshots.
- [x] Define the `background_events` field in TurnCoordinator snapshots.
- [x] Define the `request_context_ready` field in TurnCoordinator snapshots.
- [x] Define how `clear_turn` removes turn-scoped data from TurnCoordinator snapshots.

## Milestone 3: Layout and rendering
- [x] Create the three-section layout.
- [x] Add a stable Output region.
- [x] Add a short Status Line region.
- [x] Add an Input region that remains editable.
- [x] Add event-driven redraws for Output and Status.
- [x] Ensure background work does not block the visible prompt.
- [x] Render the Output pane with a `FormattedTextControl` inside a `Window`.
- [x] Give the Output pane a minimum height of 24.
- [x] Let the Output pane grow using weight-based layout.
- [x] Render assistant transcript entries with visible STX/ETX markers.
- [x] Highlight STX/ETX markers in yellow.
- [x] Highlight assistant transcript output with Bash syntax highlighting.
- [x] Render subagent transcript entries as plain text.
- [x] Render error transcript entries as plain text.
- [x] Keep transcript rendering aligned with the current buffer/renderer/viewport split.
- [x] Route transcript entries through a buffer model instead of private helper classes.
- [x] Use a dedicated transcript renderer for visible line formatting.
- [x] Drive scrolling through a viewport component.
- [x] Keep the viewport updated as new output arrives.
- [x] Preserve a stable visible transcript area while input remains editable.

## Milestone 4: Event model
- [x] Define TUI event dataclasses.
- [x] Model output events.
- [x] Model status events.
- [x] Model background completion events (now carrying optional `failure_kind` for transient-vs-fatal status distinction).
- [x] Model subagent result delivery events.
- [x] Keep event types simple and easy to test.
- [x] Add `OutputEvent` to the event model.
- [x] Add `StatusEvent` to the event model.
- [x] Add `BackgroundCompletionEvent` to the event model.
- [x] Add `SubagentResultEvent` to the event model.
- [x] Add `ErrorEvent` to the event model.
- [x] Add optional `InputDraftEvent` to the event model.
- [x] Keep event handling centered on the UI event queue.
- [x] Dispatch presentation updates from event handlers rather than rendering callbacks.
- [x] Surface mid-turn phase status (`compacting`, `working`) via `RuntimeContext.status_listener` callback (direct mutation + `application.invalidate()`, bypassing the event queue because the queue doesn't drain mid-turn).
- [ ] Add explicit scroll events for the transcript viewport.
- [ ] Ensure scroll events do not interfere with draft editing.
- [ ] Define keyboard-driven viewport navigation behavior.
- [ ] Define how viewport position is preserved across output refreshes.
- [ ] **Blocker for sub-agent feature:** drain the event queue on every redraw tick (currently drains only on background completion, which means mid-turn sub-agent events would queue without surfacing).

## Milestone 5: Integration with runtime
- [x] Connect the TUI to `MonitorApp` / `RuntimeContext`.
- [x] Keep `ConversationSession` as the session-oriented orchestration layer.
- [x] Route visible events to the Output pane.
- [x] Route runtime status to the Status Line.
- [x] Keep input handling separate from background event handling.
- [x] Define a turn completion result type.
- [x] Move LLM submission off the UI thread.
- [x] Wire completion callbacks to enqueue presentation events.
- [x] Restore idle on success.
- [x] Restore idle on failure.
- [x] Keep the UI thread as the only mutator of `TuiApp` state.
- [x] Feed runtime updates into the current UI event pipeline.
- [x] Keep background completions visible without blocking input.
- [x] Confirm transient runtime errors render through the status line and output pane.
- [ ] Verify runtime shutdown clears any queued transient UI work.

## Milestone 6: Subagent compatibility
- [x] Allow background subagent results to be injected as explicit internal context.
- [x] Avoid silently rewriting the user’s visible input.
- [x] Keep the main chat loop responsive while subagent work is running.
- [x] Support a single subagent first.
- [x] Emit a clear completion marker that the parent can detect.
- [x] Keep subagent results visible through the current snapshot-driven workflow.
- [x] Define how future subagent scrollback is surfaced in the viewport.
- [ ] Verify subagent result delivery preserves ordering with normal output.

## Milestone 7: Verification
- [x] Add tests for TUI layout construction.
- [x] Add tests for event handling.
- [x] Add tests for status updates via the runtime context status listener (`runtime_context.emit_status` → `tui.status_text`).
- [x] Add tests for responsiveness while background activity is running.
- [x] Add tests for subagent result injection as internal context.
- [x] Confirm the TUI does not break the existing CLI flow.
- [x] Add tests for the completion event states (`completed (idle)`, `failed (idle)`, `rate limited (idle)`).
- [ ] Add tests for keyboard scrolling and focus preservation.
- [ ] Add tests for event ordering under concurrent background updates.
- [x] Add tests for rate-limit denial surfacing through the TUI (via `failure_kind="rate_limited"` on the completion event).
- [x] All TUI tests use only the public interface — `enqueue_event` / `drain_events` / `status_text` / `runtime_context.emit_status`. No private (`_`-prefixed) attribute or method access.

### Coverage notes
- The transcript-content tests (which previously asserted on `_get_output_formatted_text` and `_transcript_buffer.entries`) were deleted because the transcript text has no public observable. The behavior is still exercised every time the TUI runs; visual inspection is the QA path. Locking this in via a public method would expand the API surface solely for testing.
- The `_build_completion_events` unit test was deleted; the two ends of that pipeline (constructing a `BackgroundCompletionEvent` with `failure_kind` and the routing of that event to a status update) are tested individually, so the bridge isn't separately covered.

## Notes
- Start small and keep the first implementation thin.
- Avoid over-splitting the presentation layer until the interaction model is stable.
- The TUI should be built before the subagent subsystem so the interaction contract is clear.
- The current TUI is well-positioned (~60% built) toward the agent-orchestrator target. The two remaining blockers before sub-agents land: (a) drain the event queue on every redraw tick, (b) replace the single-string `status_text` with per-agent state. See `SUBAGENT_PLAN.md`.
