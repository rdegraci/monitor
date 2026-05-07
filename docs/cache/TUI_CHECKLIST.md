# TUI_CHECKLIST

## Goal
Track the work needed to add a responsive three-section TUI to `monitor_oop`:
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
- [ ] Define the minimal `TuiApp` field set.
- [ ] Add `runtime_context` as a required `TuiApp` field.
- [ ] Add `turn_coordinator` as a required `TuiApp` field.
- [ ] Add `layout` as a required `TuiApp` field.
- [ ] Add `event_queue` as a required `TuiApp` field.
- [ ] Add `is_running` as a required `TuiApp` field.
- [ ] Add `output_buffer` as an optional later `TuiApp` field.
- [ ] Add `status_text` as an optional later `TuiApp` field.
- [ ] Add `input_draft` as an optional later `TuiApp` field.
- [ ] Add `active_task_id` as an optional later `TuiApp` field.

## Milestone 2: UI contract
- [ ] Define the Output pane responsibilities.
- [ ] Define the Status Line responsibilities.
- [ ] Define the Input pane responsibilities.
- [ ] Define how background events update the UI.
- [ ] Define how subagent results are surfaced in the UI.
- [ ] Define how the UI keeps the current user draft responsive.
- [ ] Define how `OutputEvent` is rendered into the Output pane.
- [ ] Define how `StatusEvent` is rendered into the Status Line.
- [ ] Define how `BackgroundCompletionEvent` updates the UI when background work finishes.
- [ ] Define how `SubagentResultEvent` is injected as explicit internal context.
- [ ] Define how `ErrorEvent` is surfaced without blocking the main chat loop.
- [ ] Define how optional `InputDraftEvent` keeps the current draft responsive.
- [ ] Define how TurnCoordinator owns internal context.
- [ ] Define how TurnCoordinator owns subagent results.
- [ ] Define how TurnCoordinator owns background completion state.
- [ ] Define how TurnCoordinator owns request assembly input.
- [ ] Define the structured internal-context record shape.
- [ ] Define the `id` field for internal-context records.
- [ ] Define the `source` field for internal-context records.
- [ ] Define the `kind` field for internal-context records.
- [ ] Define the `text` field for internal-context records.
- [ ] Define the `timestamp` field for internal-context records.
- [ ] Define optional `metadata` for internal-context records.
- [ ] Distinguish mostly-internal raw records from UI-visible summaries.
- [ ] Define how the TUI consumes TurnCoordinator snapshots instead of direct rendering callbacks.
- [ ] Define `begin_turn` on TurnCoordinator.
- [ ] Define `begin_turn` assigning a new turn id.
- [ ] Define `begin_turn` clearing stale turn-scoped data.
- [ ] Define `add_internal_context` on TurnCoordinator.
- [ ] Define `add_internal_context` appending structured records in order.
- [ ] Define `add_subagent_result` on TurnCoordinator.
- [ ] Define `add_subagent_result` as a thin semantic wrapper that also stores a generic internal-context record.
- [ ] Define `add_background_event` on TurnCoordinator.
- [ ] Define `add_background_event` as append-only.
- [ ] Define `mark_background_complete` on TurnCoordinator.
- [ ] Define `mark_background_complete` recording completion.
- [ ] Define `mark_background_complete` updating pending-work state.
- [ ] Define `mark_background_complete` updating background status.
- [ ] Define `snapshot` on TurnCoordinator.
- [ ] Define `snapshot` returning a read-only view.
- [ ] Define `clear_turn` on TurnCoordinator.
- [ ] Define `clear_turn` as a strict reset of turn-local state.
- [ ] Define `clear_turn` removing turn-scoped data.
- [ ] Define the `turn_id` field in TurnCoordinator snapshots.
- [ ] Define the `background_status` field in TurnCoordinator snapshots.
- [ ] Define the `has_pending_work` field in TurnCoordinator snapshots.
- [ ] Define the `internal_context_entries` field in TurnCoordinator snapshots.
- [ ] Define the `subagent_results` field in TurnCoordinator snapshots.
- [ ] Define the `background_events` field in TurnCoordinator snapshots.
- [ ] Define the `request_context_ready` field in TurnCoordinator snapshots.
- [ ] Define how `clear_turn` removes turn-scoped data from TurnCoordinator snapshots.

## Milestone 3: Layout and rendering
- [ ] Create the three-section layout.
- [ ] Add a stable Output region.
- [ ] Add a short Status Line region.
- [ ] Add an Input region that remains editable.
- [ ] Add event-driven redraws for Output and Status.
- [ ] Ensure background work does not block the visible prompt.

## Milestone 4: Event model
- [ ] Define TUI event dataclasses.
- [ ] Model output events.
- [ ] Model status events.
- [ ] Model background completion events.
- [ ] Model subagent result delivery events.
- [ ] Keep event types simple and easy to test.
- [ ] Add `OutputEvent` to the event model.
- [ ] Add `StatusEvent` to the event model.
- [ ] Add `BackgroundCompletionEvent` to the event model.
- [ ] Add `SubagentResultEvent` to the event model.
- [ ] Add `ErrorEvent` to the event model.
- [ ] Add optional `InputDraftEvent` to the event model.

## Milestone 5: Integration with runtime
- [ ] Connect the TUI to `MonitorApp` / `RuntimeContext`.
- [ ] Keep `ConversationSession` as the session-oriented orchestration layer.
- [ ] Route visible events to the Output pane.
- [ ] Route runtime status to the Status Line.
- [ ] Keep input handling separate from background event handling.

## Milestone 6: Subagent compatibility
- [ ] Allow background subagent results to be injected as explicit internal context.
- [ ] Avoid silently rewriting the user’s visible input.
- [ ] Keep the main chat loop responsive while subagent work is running.
- [ ] Support a single subagent first.
- [ ] Emit a clear completion marker that the parent can detect.

## Milestone 7: Verification
- [ ] Add tests for TUI layout construction.
- [ ] Add tests for event handling.
- [ ] Add tests for output/status/input updates.
- [ ] Add tests for responsiveness while background activity is running.
- [ ] Add tests for subagent result injection as internal context.
- [ ] Confirm the TUI does not break the existing CLI flow.

## Notes
- Start small and keep the first implementation thin.
- Avoid over-splitting the presentation layer until the interaction model is stable.
- The TUI should be built before the subagent subsystem so the interaction contract is clear.
