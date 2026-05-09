# TUI_PLAN

## Goal
Build a prompt_toolkit-based terminal UI for `monitor_oop` with three sections:
- Output
- Status Line
- Input

The TUI should stay responsive while background work, including subagent activity, is happening.
The next evolution of the TUI is to move user turn execution off the UI thread so LLM submissions can run in the background while working is displayed visibly in the interface.
The TUI observes `TurnCoordinator` snapshots as the per-turn coordination boundary for internal context, subagent results, and background completion state, rather than directly owning request assembly logic or direct rendering callbacks.
The current UI is prompt_toolkit-based and implemented: `MonitorApp/run_tui` delegates into the Application-backed run path with `output_area`, `status_control`, and `input_area`, and the TUI includes a simple loop that accepts draft input and exits through the Application flow.
The TUI uses injectable I/O helpers through prompt_toolkit UI components and session plumbing so input, output, and status behavior can be swapped cleanly without coupling the core loop to a specific terminal backend.
The TUI uses `build_app(quiet_bootstrap=True)` for quiet startup, and runtime logging is suppressed while the TUI session is active.
The next implementation step introduces an event-driven completion path that can restore the Status Line to idle after turn completion, rather than relying on synchronous UI-thread state changes.

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
- The next turn execution model should submit the user turn to a background worker, capture its completion in a small result object such as `TurnCompletionResult`, and use that completion event to restore the Status Line to idle.

## Event Model
- `OutputEvent`: append visible assistant content, progress, and general output to the Output area.
- `StatusEvent`: update the Status Line without disturbing the current input draft.
- `BackgroundCompletionEvent`: notify the UI that background work has completed.
- `SubagentResultEvent`: surface subagent results as explicit internal context and, when appropriate, visible output.
- `ErrorEvent`: report failures in the Output area and Status Line as needed.
- `InputDraftEvent` (optional): represent transient input draft updates without mutating visible prompt text.
- `TurnCompletionEvent`: carry a completion result such as `TurnCompletionResult` so the UI can finalize the turn and return the Status Line to idle in an event-driven way.

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
- The TUI consumes `TurnCoordinator` snapshots with the interface `begin_turn/add_internal_context/add_subagent_result/add_background_event/mark_background_complete/snapshot/clear_turn`.
- The basic UI contract is implemented as a prompt_toolkit `Application` with distinct `output_area`, `status_control`, and `input_area` regions, with richer layout behavior reserved for later enhancements.
- The interactive loop and prompt_toolkit session plumbing are implemented as the current control surface for the TUI.
- The next evolution should move LLM submission and turn processing off the UI thread, while preserving event-driven status restoration and completion handling.

## Likely Requirements
- A stable layout with three distinct regions.
- A way to append to Output without blocking input.
- A way to update Status without disturbing the current draft prompt.
- An event path for background completion notifications.
- A clean way to represent internal context separately from user-visible output.
- TurnCoordinator should expose the per-turn internal context and completion state that the TUI observes through snapshots, instead of having the TUI assemble requests directly.
- The snapshot interface should provide `begin_turn`, `add_internal_context`, `add_subagent_result`, `add_background_event`, `mark_background_complete`, `snapshot`, and `clear_turn`.
- The interactive loop, richer layout behavior, and subagent execution flow remain future work.
- The next turn execution step should produce a compact completion result object, such as `TurnCompletionResult`, that can be consumed by the UI event loop to finalize the turn and transition the Status Line back to idle.

## Build Order
1. Define the UI contract.
2. Build the three-pane layout.
3. Add status updates.
4. Add background event rendering.
5. Integrate subagent completion events.
6. Add background turn execution for LLM submissions and event-driven idle restoration.

## Open Questions
- Should Output be append-only or support richer formatting?
- Should Status be a single line or a small fixed-height area?
- Should Input preserve history and editing shortcuts?
- Should background events be queued or shown immediately?
- Should subagent results appear in Output before being injected into the LLM flow?
- Should turn completion return a dedicated result object, such as `TurnCompletionResult`, or a broader turn state envelope?

## Success Criteria
- The UI remains usable while background work runs.
- Input stays editable and responsive.
- Output and Status can update independently.
- The UI can show subagent progress and completion.
- The TUI supports future orchestration without forcing hidden prompt mutations.
- Completion events can restore the Status Line to idle after background turn execution finishes, even though the current implementation remains synchronous today.
