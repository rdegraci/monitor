# TUI_PLAN

## Goal
Build a prompt_toolkit-based terminal UI for `monitor_oop` with three sections:
- Output
- Status Line
- Input

The TUI should stay responsive while background work, including subagent activity, is happening.
The UI is prompt_toolkit-based and implemented: `MonitorApp/run_tui` delegates into the Application-backed run path with `output_area`, `status_control`, and `input_area`, and the TUI includes a simple loop that accepts draft input and exits through the Application flow.
The TUI uses injectable I/O helpers through prompt_toolkit UI components and session plumbing so input, output, and status behavior can be swapped cleanly without coupling the core loop to a specific terminal backend.
The TUI uses `build_app(quiet_bootstrap=True)` for quiet startup, and runtime logging is suppressed while the TUI session is active.
The current implementation routes visible output through the implemented prompt_toolkit transcript pipeline, which is split into a transcript buffer, transcript renderer, and transcript viewport, and remaining work focuses on polish, mouse support, and event-driven completion details rather than basic transcript rendering.

## TuiApp Core Fields
The minimal `TuiApp` fields are:
- `runtime_context` (implemented)
- `turn_coordinator` (implemented)
- `layout` (implemented)
- `event_queue` (implemented)
- `is_running` (implemented)

Optional later fields may include:
- `status_text`
- `input_draft`
- `active_task_id`

## Core Interaction Model
- The Input area is where the user types prompts and commands.
- The Output area shows assistant responses, progress messages, and other visible events.
- The Status Line shows short-lived operational state such as mode, active work, and subagent progress.
- The interactive loop reads draft input, updates the current turn state, and runs through the Application-backed TUI path.
- The current output path uses the implemented transcript buffer/renderer/viewport split rather than direct OutputEvent-driven rendering, and assistant transcript entries are rendered with visible STX/ETX markers while error and subagent transcript entries remain plain text.
- PageUp/PageDown move through the transcript viewport, while the follow-tail behavior keeps the view pinned to new output when the user is at the end of the transcript.
- The current implementation updates the Status Line from the existing event flow and turn lifecycle state, and completion handling restores the UI to idle once the turn finishes.

## Event Model
- `TranscriptEvent`: append visible assistant content, progress, and general output to the Output area through the current transcript pipeline.
- `StatusEvent`: update the Status Line without disturbing the current input draft.
- `BackgroundCompletionEvent`: notify the UI that background work has completed.
- `SubagentResultEvent`: surface subagent results as explicit internal context and, when appropriate, visible output.
- `ErrorEvent`: report failures in the Output area and Status Line as needed.
- `InputDraftEvent` (optional): represent transient input draft updates without mutating visible prompt text.
- `TurnCompletionEvent`: carry a completion result such as `TurnCompletionResult` so the UI can finalize the turn and return the Status Line to idle in an event-driven way.

The TUI currently handles queued events synchronously; background notifications are drained and applied on the main UI path rather than through a separate asynchronous rendering pipeline.
The loop uses prompt_toolkit Application state and ConversationSession integration to read input and emit output while keeping the core UI behavior testable and backend-agnostic.
The transcript pipeline is implemented with the prompt_toolkit buffer, renderer, and viewport, which own the formatting and scrolling behavior for assistant, error, and subagent transcript entries.

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
- Avoid hidden mutation of the user's visible prompt text.
- Treat background work as event-driven updates.
- Keep the TUI compatible with future subagent support.
- Inject subagent results as explicit internal context rather than hidden user text.
- Ensure the parent remains responsive while background work runs (LLM submission runs on a `ThreadPoolExecutor` worker; the UI thread is the only mutator of `TuiApp` state).
- Internal context records have a structured shape with `id`, `source`, `kind`, `text`, `timestamp`, and optional `metadata`.
- The UI may show summaries or status notices derived from those records while the raw records remain mostly internal.
- The TUI consumes `TurnCoordinator` snapshots with the interface `begin_turn/add_internal_context/add_subagent_result/add_background_event/mark_background_complete/snapshot/clear_turn`.
- The UI contract is a prompt_toolkit `Application` with distinct output/status/input regions.

## Status State Machine
The TUI status indicator has these states with color coding:

| State                  | Color  | Trigger                                                                                  |
| ---------------------- | ------ | ---------------------------------------------------------------------------------------- |
| `idle`                 | green  | Initial state; ready for input.                                                          |
| `working`              | yellow | User submitted; a turn is in flight (between the worker-thread `submit_input` call and the worker's `BackgroundCompletionEvent`). |
| `compacting`           | yellow | Mid-turn: the proactive compaction is running summarization before the main LLM call.    |
| `completed (idle)`     | green  | Successful turn finished; ready for the next.                                            |
| `failed (idle)`        | red    | Generic failure (non-rate-limit).                                                        |
| `rate limited (idle)`  | yellow | Rate-limit denial caught from `RateLimitDeniedError`; transient, retry soon. Surfaced via `failure_kind="rate_limited"` on the `BackgroundCompletionEvent`. The full denial message (current/limit/retry_after) appears as a red transcript line. |

The `compacting`/`working` transitions are emitted by `ConversationSession._maybe_compact_history` through `RuntimeContext.emit_status`, which calls the listener `TuiApp` registered on construction. The listener mutates `status_text` directly and calls `application.invalidate()` — this bypasses the event queue because the queue doesn't drain mid-turn.

## Likely Requirements
- A stable layout with three distinct regions.
- A way to append to Output without blocking input.
- A way to update Status without disturbing the current draft prompt.
- An event path for background completion notifications.
- A clean way to represent internal context separately from user-visible output.
- TurnCoordinator should expose the per-turn internal context and completion state that the TUI observes through snapshots, instead of having the TUI assemble requests directly.
- The snapshot interface should provide `begin_turn`, `add_internal_context`, `add_subagent_result`, `add_background_event`, `mark_background_complete`, `snapshot`, and `clear_turn`.
- The interactive loop, richer layout behavior, mouse support, and subagent execution flow remain future work.
- The next turn execution step should produce a compact completion result object, such as `TurnCompletionResult`, that can be consumed by the UI event loop to finalize the turn and transition the Status Line back to idle.

## Build Order
1. Define the UI contract.
2. Build the three-pane layout.
3. Add status updates.
4. Add background event rendering.
5. Integrate subagent completion events.
6. Add background turn execution for LLM submissions and event-driven idle restoration.

## Open Questions
- Should Output support richer formatting beyond the current STX/ETX-marked assistant blocks with Bash syntax highlighting?
- Should mouse interactions support transcript selection in addition to wheel scrolling?
- For sub-agent dispatch (when implemented): should sub-agent transcript output appear in the parent's transcript live, or only after parent processing? Current scaffold supports both via `SubagentTranscriptEvent`.

## Resolved Decisions
- **Background events drain timing:** Currently drains only on completion. **Needs fix** before sub-agents land — drain on every redraw tick.
- **Turn completion shape:** `TurnCompletionResult` with `failure_kind` for distinct rate-limit rendering.
- **Status indicator:** single string `status_text` per the matrix above. **Needs evolution** to per-agent state for sub-agent support (a `dict[task_id, state]` or `StatusBoard` object).
- **Mid-turn phase updates:** direct-mutation status listener installed by `TuiApp`, bypasses the event queue.
- **Test boundary:** public interface only (`enqueue_event` / `drain_events` / `status_text` / `runtime_context.emit_status`).

## Success Criteria
- The UI remains usable while background work runs. ✓
- Input stays editable and responsive. ✓
- Output and Status can update independently. ✓
- Status indicator distinguishes idle / working / compacting / completed / failed / rate-limited states with consistent color semantics. ✓
- The TUI supports future orchestration without forcing hidden prompt mutations. ✓
- Completion events restore the Status Line to a `(idle)` state after background turn execution. ✓
- Rate-limit denials produce a visible, distinct, transient indicator (not the generic red `failed`). ✓
- (Pending sub-agent work) Per-agent status indicators and mid-turn event-queue draining.
