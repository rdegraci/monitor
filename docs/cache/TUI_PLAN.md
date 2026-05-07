# TUI_PLAN

## Goal
Build a prompt_toolkit-based terminal UI for `monitor_oop` with three sections:
- Output
- Status Line
- Input

The TUI should stay responsive while background work, including subagent activity, is happening.
The TUI should observe `TurnCoordinator` snapshots as the per-turn coordination boundary for internal context, subagent results, and background completion state, rather than directly owning request assembly logic or direct rendering callbacks.
The current UI is prompt_toolkit-based and implemented: `MonitorApp/run_tui` now delegates into the Application-backed run path with `output_area`, `status_control`, and `input_area`, and the TUI includes a simple loop that accepts draft input and exits through the Application flow.
The TUI uses injectable I/O helpers through prompt_toolkit UI components and session plumbing so input, output, and status behavior can be swapped cleanly without coupling the core loop to a specific terminal backend.
The TUI uses `build_app(quiet_bootstrap=True)` for quiet startup, and runtime logging is suppressed while the TUI session is active.

## TuiApp Core Fields
The minimal `TuiApp` fields are:
- `runtime_context` (implemented)
- `turn_coordinator` (implemented)
- `layout` (implemented)
- `event_queue` (implemented)
- `is_running` (implemented)

Optional later fields may include:
- `output_buffer`
- `status_text`
- `input_draft`
- `active_task_id`

## Core Interaction Model
- The Input area is where the user types prompts and commands.
- The Output area shows assistant responses, progress messages, and other visible events.
- The Status Line shows short-lived operational state such as mode, active work, and subagent progress.
- The interactive loop reads draft input, updates the current turn state, and runs through the Application-backed TUI path.

## Event Model
- `OutputEvent`: append visible assistant content, progress, and general output to the Output area.
- `StatusEvent`: update the Status Line without disturbing the current input draft.
- `BackgroundCompletionEvent`: notify the UI that background work has completed.
- `SubagentResultEvent`: surface subagent results as explicit internal context and, when appropriate, visible output.
- `ErrorEvent`: report failures in the Output area and Status Line as needed.
- `InputDraftEvent` (optional): represent transient input draft updates without mutating visible prompt text.

The TUI currently handles queued events synchronously; background notifications are drained and applied on the main UI path rather than through a separate asynchronous rendering pipeline.
The loop uses prompt_toolkit Application state and ConversationSession integration to read input and emit output while keeping the core UI behavior testable and backend-agnostic.

## TurnCoordinator Snapshot Fields
The TUI observes turn-scoped state through `TurnCoordinator` snapshots with these fields:
- `turn_id` (implemented)
- `background_status` (implemented)
- `has_pending_work` (implemented)
- `internal_context_entries` (implemented)
- `subagent_results` (implemented)
- `background_events` (implemented)
- `request_context_ready` (implemented)

Turn lifecycle notes: `begin_turn` assigns a new turn id and clears stale turn-scoped data; `mark_background_complete` records task completion, updates pending-work state, and advances the background status. `add_internal_context` appends structured records in order. `add_subagent_result` is a thin semantic wrapper that also stores a generic internal-context record. `add_background_event` is append-only for turn-scoped lifecycle events. `snapshot` returns a read-only view. `clear_turn` is a strict reset of turn-local state.
After each turn, `clear_turn` removes turn-scoped data so the next turn starts with a clean snapshot boundary.

## Design Principles
- Keep the user input experience responsive.
- Keep Output and Status updates independent from Input editing.
- Avoid hidden mutation of the user’s visible prompt text.
- Treat background work as event-driven updates.
- Keep the TUI compatible with future subagent support.
- Inject subagent results as explicit internal context rather than hidden user text.
- Ensure the parent remains responsive while background work runs.
- Internal context records should have a structured shape with `id`, `source`, `kind`, `text`, `timestamp`, and optional `metadata`.
- The UI may show summaries or status notices derived from those records while the raw records remain mostly internal.
- The TUI should consume `TurnCoordinator` snapshots with the interface `begin_turn/add_internal_context/add_subagent_result/add_background_event/mark_background_complete/snapshot/clear_turn`.
- The basic UI contract is implemented as a prompt_toolkit `Application` with distinct `output_area`, `status_control`, and `input_area` regions, with richer layout behavior reserved for later.
- The interactive loop and prompt_toolkit session plumbing are implemented as the current control surface for the TUI.

## Likely Requirements
- A stable layout with three distinct regions.
- A way to append to Output without blocking input.
- A way to update Status without disturbing the current draft prompt.
- An event path for background completion notifications.
- A clean way to represent internal context separately from user-visible output.
- TurnCoordinator should expose the per-turn internal context and completion state that the TUI observes through snapshots, instead of having the TUI assemble requests directly.
- The snapshot interface should provide `begin_turn`, `add_internal_context`, `add_subagent_result`, `add_background_event`, `mark_background_complete`, `snapshot`, and `clear_turn`.
- The interactive loop, richer layout behavior, and subagent execution flow remain future work.

## Build Order
1. Define the UI contract.
2. Build the three-pane layout.
3. Add status updates.
4. Add background event rendering.
5. Integrate subagent completion events.

## Open Questions
- Should Output be append-only or support richer formatting?
- Should Status be a single line or a small fixed-height area?
- Should Input preserve history and editing shortcuts?
- Should background events be queued or shown immediately?
- Should subagent results appear in Output before being injected into the LLM flow?

## Success Criteria
- The UI remains usable while background work runs.
- Input stays editable and responsive.
- Output and Status can update independently.
- The UI can show subagent progress and completion.
- The TUI supports future orchestration without forcing hidden prompt mutations.
