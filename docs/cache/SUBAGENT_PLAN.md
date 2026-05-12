# SUBAGENT_PLAN

## Goal
Add a lightweight subagent workflow to the OOP Monitor app by running a second isolated `monitor_oop` process and feeding its results back into the main app as explicit internal context.

The initial goal is testing-oriented: support one subagent at a time, keep the implementation process-separated, and preserve the main app's responsiveness while background work completes.

## Core Idea
The subagent is not an in-process object graph nested inside the main runtime.
Instead, it is a separate `monitor_oop` process that:
- receives a prompt or task
- runs independently
- emits a clear completion marker
- returns structured output to the parent process

The parent app treats subagent output as internal context, not hidden user text.

## Internal Context Records
Internal context is represented as structured records so the parent can track what was added and why.

Each internal context entry should include:
- `id`
- `source`
- `kind`
- `text`
- `timestamp`
- optional `metadata`

These entries are primarily internal to request construction and coordination. The TUI may surface summaries or status notices about them, but the full internal context should stay mostly hidden from the user-facing prompt and preserve the honesty of the visible draft.

## TurnCoordinator
TurnCoordinator is the thin coordinator object for a single conversational turn.

It owns:
- per-turn internal context
- subagent results for the current turn
- background completion state
- request assembly input

It is intentionally separate from `RuntimeContext` and `ConversationSession`.

`RuntimeContext` should continue to represent broader application/runtime state, and `ConversationSession` should continue to represent the ongoing conversation history and session-level data. `TurnCoordinator` should only coordinate what is needed to assemble and complete one turn, including any subagent-derived internal context that must be injected into the request-construction path.

### TurnCoordinator Intake and Reset Behavior
`add_internal_context` appends structured records in order.
`add_subagent_result` is a thin semantic wrapper that also stores a generic internal-context record.
`add_background_event` is append-only for turn-scoped lifecycle events.
`snapshot` returns a read-only view of the current turn state.
`clear_turn` is a strict reset of turn-local state.

### TurnCoordinator Snapshot Interface
`TurnCoordinator` should expose a simplified snapshot-oriented interface:

- `begin_turn`
- `add_internal_context`
- `add_subagent_result`
- `add_background_event`
- `mark_background_complete`
- `snapshot`
- `clear_turn`

The TUI consumes `TurnCoordinator` snapshots rather than being coupled to rendering callbacks. This keeps the UI focused on presentation while the coordinator remains the source of truth for per-turn state, and the existing snapshot-driven turn presentation and event handling now form the basic scaffolding for that flow.

### TurnCoordinator Lifecycle Notes
`begin_turn` assigns a new turn id and clears stale turn-scoped data before starting the turn.
`mark_background_complete` records task completion, updates pending-work state, and advances the background status.

### TurnCoordinator Snapshot Fields
The `snapshot` should include:
- `turn_id`
- `background_status`
- `has_pending_work`
- `internal_context_entries`
- `subagent_results`
- `background_events`
- `request_context_ready`

`clear_turn` should remove turn-scoped data after each turn so the next turn starts from a clean coordinator state.

## Design Principles
- Keep the parent and subagent isolated as separate OS processes.
- Prefer explicit communication over implicit shared state.
- Keep the user-facing prompt honest; do not secretly rewrite visible user text.
- Inject subagent results into the LLM request as explicit internal context.
- Keep the main chat loop responsive while background work runs.
- Start with one subagent only.
- Keep the initial implementation simple and debuggable.

## User Interface Direction
Build a TUI with three regions:
- Output
- Status Line
- Input

The app now exposes the TUI through the `--tui` flag, and the basic app-level TUI integration is present. The scaffold is wired through `MonitorApp/run_tui` with injectable I/O helpers, and the app now includes an interactive draft-input loop while the UI is active. The scaffold keeps the main loop responsive while the UI is active and provides a visible surface for turn state and background activity.

### Output
Used for:
- assistant responses
- subagent progress updates
- completion notices
- internal event messages that should be visible to the user
- summaries of internal context records when appropriate

### Status Line
Used for:
- current app mode
- subagent running state
- pending background work
- model or task hints
- short operational status
- internal context availability notices

### Input
Used for:
- the user’s current draft prompt
- normal interactive command entry

The TUI remains responsive while a subagent is running, and the initial TUI scaffold now exists at a basic level, with the three regions in place and snapshot-driven updates wired into the turn flow.

## Event Flow
The UI and background system exchange explicit events rather than implicit shared state.

Event types:
- `OutputEvent`
- `StatusEvent`
- `BackgroundCompletionEvent`
- `SubagentResultEvent`
- `ErrorEvent`
- optional `InputDraftEvent`

Suggested flow:
1. The user edits the draft input.
2. The UI may emit an `InputDraftEvent` to reflect the current draft state.
3. The parent launches a background subagent task.
4. The subagent process emits output and a deterministic completion marker.
5. The parent watcher detects completion and raises a `BackgroundCompletionEvent`.
6. The completed subagent payload is wrapped as a `SubagentResultEvent`.
7. The UI receives `OutputEvent` and `StatusEvent` updates as needed.
8. If anything fails, the system emits an `ErrorEvent`.

This event model keeps the parent responsive and makes background activity visible without blocking input. The basic event-handling path is now in place through the TUI and TurnCoordinator snapshot updates, while richer background orchestration remains future work.

## Subagent Execution Model
The parent app launches a second `monitor_oop` process with a task prompt.

The subagent process should:
- run with its own config/history/prompt state
- remain isolated from the parent process
- print a recognizable completion marker such as `Generated: <timestamp>`
- emit the result in a form the parent can read reliably

The parent app should:
- launch the subagent process asynchronously
- keep accepting user input
- watch for subagent completion
- inject the returned output into the LLM flow as explicit internal context
- avoid waiting for the user to type again before handling subagent results

The process-isolation and single-subagent execution goals remain future work for the full workflow, even though the initial TUI and turn-coordination scaffolding now exists.

## Completion Signaling
Use a deterministic completion marker from the subagent output stream so the parent can detect when work is done.

The marker must be:
- stable
- easy to grep
- emitted only when the subagent has completed the task

This is intended as a simple testing-oriented signal, not a long-term IPC protocol.

## Internal Context Injection
When the subagent completes, its output should be added to the parent's LLM request as explicit internal context.

Do not:
- silently rewrite the user's typed input
- hide the fact that the model is receiving additional context
- make the visible prompt text differ from what the user entered

Instead:
- keep the user draft intact
- combine it with subagent output only at request-construction time
- treat the subagent result as structured context or an internal message source

## Recommended Build Order
1. Build the TUI first.
2. Define how Output, Status Line, and Input update independently.
3. Define how background events are surfaced in the UI.
4. Add the subagent launcher and completion watcher.
5. Feed subagent output into the main LLM pipeline as internal context.

The TUI-focused milestones are now implemented at a basic level, and the next steps are to deepen the background launcher and process-isolated subagent flow.

## TUI Requirements
The TUI should support:
- a live output pane
- a status pane that can reflect background activity
- an input area that stays usable while background work runs
- background event updates without blocking the UI

Potential implementation directions:
- use a layout-driven terminal UI
- keep user input and output rendering separated
- make the background watcher an event source for the UI

## Process Isolation
To keep the system predictable:
- use separate process state for parent and subagent
- avoid shared mutable in-memory state
- keep config/history/prompt files isolated if needed
- prefer explicit environment variables or launch arguments for subagent configuration differences

The full process-isolation boundary is still a future-work goal for the subagent workflow, even though the current scaffolding already separates turn coordination and UI event handling from request assembly.

## Open Questions
- Should the subagent output be shown immediately in Output, or only after parent processing?
- Should the parent queue multiple background events, or only allow one subagent at a time?
- Should the completion marker be human-readable only, or paired with structured output metadata?
- Should the TUI show a visible “subagent running” indicator in the Status Line?
- How should the parent distinguish between user-visible output and internal context events?

## Suggested First Milestone
Start with a minimal TUI that has:
- Output pane
- Status Line
- Input pane
- a simple background event update path

Then add the single-subagent process launcher and completion detection.

The minimal TUI milestone is now in place at a basic level, and the remaining work is to expand the launcher, completion detection, and process-isolated subagent handling.

## Success Criteria
- The main chat loop remains responsive while a subagent runs.
- The subagent runs as a separate `monitor_oop` process.
- The parent can detect subagent completion without waiting for user input.
- Subagent results can be injected into the parent LLM flow as explicit internal context.
- The TUI cleanly separates Output, Status Line, and Input.
- The user’s visible draft prompt remains honest and unchanged.
- The system stays simple enough to test with one subagent first.

The TUI separation and snapshot-driven turn coordination are now established at a basic level, while the single-subagent and full process-isolation milestones remain the next major targets.
