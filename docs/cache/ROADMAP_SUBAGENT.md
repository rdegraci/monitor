# ROADMAP_SUBAGENT

## Purpose
This roadmap summarizes the evolution of the sub-agent topology in `monitor_oop`, what is implemented today, and what remains.

It is intended as a narrative companion to:
- `docs/cache/PLAN_SUBAGENT.md`
- `docs/cache/CHECKLIST_SUBAGENT.md`

## Where we have been

The sub-agent design began as a testing-oriented goal: launch a second `monitor_oop` process, capture its output, and feed it back into the main app as explicit internal context. The original design (an early version of `PLAN_SUBAGENT.md`) proposed a stdout-text-marker IPC (`Generated: <timestamp>`) as a placeholder while the broader interaction model was worked out.

As the OOP refactor and TUI work landed, the building blocks for sub-agent integration accumulated incrementally — most of them not as explicit "sub-agent work" but as general infrastructure that turned out to fit the sub-agent use case exactly. The text-marker IPC was superseded by a JSON Lines design once the wire protocol was fully thought through.

## What exists today

The current codebase has roughly **60% of the sub-agent topology already built**, even though no sub-agent process has yet been launched. The pieces are not labeled as "sub-agent" code — they are general-purpose scaffolding that the sub-agent design will plug into.

### Built (load-bearing for sub-agents)

- **TUI three-pane architecture.** `TuiApp` with `output_area`, `status_control`, and `input_area` widgets wrapped in a prompt_toolkit `Application`. Worker-thread execution via `ThreadPoolExecutor` keeps the UI responsive.

- **Typed presentation events.** `UserTranscriptEvent`, `AssistantTranscriptEvent`, `ErrorTranscriptEvent`, `SubagentTranscriptEvent`, `StatusEvent`, `BackgroundCompletionEvent`, `SubagentResultEvent`, `ErrorEvent`, `InputDraftEvent`, `OutputEvent`. Each event carries a `task_id` (where relevant) for correlation. These map 1:1 to the JSON event shapes that will arrive over the sub-agent IPC.

- **`TurnCoordinator` with internal-context queue.** `add_internal_context`, `add_subagent_result`, `add_background_event`, `mark_background_complete`, `snapshot`, `clear_turn`. Snapshot fields include `internal_context_entries`, `subagent_results`, `background_events`, `request_context_ready`, `has_pending_work`. Sub-agent results queue into `internal_context_entries` pending the next LLM turn.

- **`InternalContextEntry` structured records** carrying `id`, `source`, `kind`, `text`, `timestamp`, and optional `metadata`.

- **Status state machine.** `idle` (green) → `working` (yellow) → `compacting` (yellow) → `working` (yellow) → `completed (idle)` (green) / `failed (idle)` (red) / `rate limited (idle)` (yellow). Distinguishes transient (yellow) from fatal (red) failures. Sub-agent failures map naturally onto this matrix.

- **`RuntimeContext.status_listener` callback.** `TuiApp` installs itself as the listener at construction. Mid-turn phase transitions (`compacting`, `working`) emitted via `RuntimeContext.emit_status` bypass the event queue (direct mutation + `application.invalidate()`) and surface immediately. In `--agent` mode, the same listener will write `{"event": "status", ...}` lines to stdout — same hook, different sink.

- **`failure_kind` plumbed through.** `TurnCompletionResult.failure_kind` and `BackgroundCompletionEvent.failure_kind` are optional fields routed through `_build_completion_events` and `_route_presentation_event`. The TUI uses `"rate_limited"` to drive a distinct yellow indicator; sub-agent failures (timeout, crash, depth exceeded) will use additional `failure_kind` values.

- **Tool-call cluster preservation across compaction.** `ConversationBoundaryTracker` keeps complete assistant + tool-call + tool-result clusters together. `LLMRequestBuilder` emits `tool_calls`, `tool_call_id`, and `name` fields end-to-end. This is critical because sub-agent results enter the parent's conversation as `tool`-role messages with the matching `tool_call_id` from the spawning tool call — the cluster must survive compaction or the parent LLM loses the link between the spawn and the result.

- **Structured exception types crossing process boundaries.** `RateLimitDeniedError` is the model: typed fields (`reason`, `model`, `current`, `limit`, `retry_after_seconds`), `__str__` for human display, `str(exc)` is easy to serialize over JSON. Sub-agent error events will follow the same shape.

- **Tool framework ready for `spawn_subagent`.** `ToolRegistry`, `ToolService`, `ToolCallHandler` already support registering tools, parsing tool calls from LLM responses, executing them, and threading results back. Adding the `spawn_subagent` tool is a configuration step on the orchestrator's tool registry, not new framework code.

- **Compaction subsystem ready for asynchronous tool-result injection.** Compaction runs proactively before the LLM call, preserves boundary-aligned tail units, summarizes via a separate LLM call with a deterministic fallback. When sub-agent results are injected into `internal_context_entries`, they become tool-role messages in history — the same shape compaction already handles.

### Not yet built (sub-agent-specific work)

- **`--agent` mode in `__main__.py`.** A third mode alongside `--tui` and the default REPL. Reads JSON commands from stdin, dispatches each via the existing `ConversationSession`, writes JSON events to stdout.

- **`SubagentRunner` (infrastructure layer).** Owns one subprocess. Spawns `python -m monitor_oop --agent`. A daemon reader thread parses JSON events from stdout and enqueues matching TUI events. `send(command_dict)` writes to stdin. `shutdown(timeout)` sends graceful shutdown then kills.

- **`SubagentService` (infrastructure layer).** Manages multiple `SubagentRunner` instances. `spawn(prompt) -> task_id`, `cancel(task_id)`, `shutdown_all()`. Wired into `RuntimeContext`.

- **`spawn_subagent` tool.** Registered on the orchestrator's tool registry only (not on children). When called by the LLM, routes to `SubagentService.spawn(...)` and registers a callback so the eventual `result` event becomes the tool-call return value. Recursion depth controlled via `MONITOR_AGENT_DEPTH` env var.

- **Event-queue mid-turn drain (BLOCKER).** Today the TUI's event queue drains only when a `BackgroundCompletionEvent` triggers it. With multiple async sub-agents emitting events while the parent's own LLM call is running, those events sit in the queue until the parent completes. This must be fixed before sub-agents can usefully surface live updates. Fix: drain on every redraw tick, or have `enqueue_event` schedule a drain via `application.invalidate()`.

- **Multi-worker `ThreadPoolExecutor` + per-agent status state.** The current TUI is `max_workers=1` and has a single-string `status_text`. For concurrent sub-agents, both need to expand: `max_workers=N` and a `dict[task_id, state]` (or `StatusBoard` object) the status line renders.

- **Auto-flush evaluator + `process_pending_context()`.** The interaction model where the orchestrator auto-dispatches pending sub-agent results to the LLM whenever the input field is empty. Includes:
  - An evaluator that runs on event-queue drain + a periodic safety-net timer.
  - A `process_pending_context()` method on `ConversationSession` that flushes `internal_context_entries` to the LLM with no new user message (uses `previous_response_id` chain).
  - Modification to `process_user_input` to drain `internal_context_entries` ahead of the user's message in chronological order.
  - Debounce (~200–500 ms) to batch rapid-fire sub-agent completions.
  - `[N queued]` indicator in the status line when results are pending.

## What changed along the way

A few important shifts happened during the design and implementation process:

1. **IPC moved from text marker to structured JSON.** The original design used a `Generated: <timestamp>` stdout marker as the completion signal. Once the broader event protocol was thought through (status, transcript, tool_call, result, error, exited), JSON Lines over stdin/stdout became the obvious unified transport. The text-marker design was retired before any code was written for it.

2. **Sub-agent scaffolding was built as general TUI infrastructure.** Rather than adding a "sub-agent mode" as a separate feature, the events, coordinator, and status state machine were designed to support sub-agents from day one without naming them as such. This means much of the work that looks like "TUI development" in `TUI_CHECKLIST.md` was actually load-bearing for sub-agents.

3. **The `spawn_subagent` interface became a tool call.** Earlier framings imagined a separate orchestration grammar. The shift to "sub-agent dispatch is just another tool the LLM calls" simplifies the parent's LLM contract and means no new LLM-side abstractions need to be introduced. The orchestrator LLM uses `spawn_subagent` the same way it uses `weather` or any other registered tool.

4. **The interaction model gained the user right-of-way contract.** Earlier framings assumed sub-agent results would be auto-injected whenever they arrived. The current model (`PLAN_SUBAGENT.md::Auto-Flush Interaction Model`) defers auto-dispatch while the user is composing — clear UX contract instead of a hidden race between user and orchestrator.

5. **Tool-call clusters became compaction-safe.** A pre-existing bug stripped `tool_calls` / `tool_call_id` / `name` from messages at the request layer. Fixing it (so the boundary tracker's careful cluster preservation actually survives into the LLM request) was done as compaction work, but it's load-bearing for sub-agents: sub-agent results enter the parent's history as `tool`-role messages tied to their spawning tool call, and the cluster must survive compaction.

## Current implementation audit

Using the same review categories as the plan and checklist:

- **Confirmed gaps:**
  - The event queue does not drain mid-turn. Blocker for any usable sub-agent live UI.
  - The TUI executor is single-worker.
  - The TUI status state is a single string field, not per-agent.
  - No subprocess management code yet (`SubagentRunner`, `SubagentService`).
  - No `--agent` entry mode in `__main__.py`.
  - No `spawn_subagent` tool in the tool registry.
  - No auto-flush evaluator; pending `internal_context_entries` are queued but never automatically dispatched.

- **Design choices to confirm:**
  - One-shot vs. long-running sub-agent pool. Recommended first step: one-shot. Optimize to a pool only if Python startup cost (~150 ms) matters.
  - Debounce window for auto-flush. Recommended starting point: 300 ms.
  - Whether intermediate `transcript` events from sub-agents should appear live in the parent's transcript or only at completion. Open.
  - How "cancel sub-agent" is surfaced to the user. Open.

- **Product decisions needed:**
  - Whether the orchestrator should default to enabling `spawn_subagent` recursion in child instances (current proposal: opt-in via `MONITOR_AGENT_DEPTH`, default off in children).

- **Intentional separations:**
  - Sub-agent dispatch is a tool call, not a separate grammar.
  - Sub-agent results are `tool`-role messages, not synthetic user messages.
  - Sub-agent process is OS-isolated, not an in-process object graph.

## What remains to be done

In rough dependency order:

1. **Fix the event-queue mid-turn drain.** Smallest change, biggest unlock. Without it, sub-agent updates can't surface while the parent is busy.

2. **Add `--agent` mode.** Read one `run_task` from stdin, dispatch through `ConversationSession`, emit a single `result` event. No streaming, no concurrency.

3. **Build `SubagentRunner`.** Spawn the subprocess, parse JSON events, enqueue matching TUI events. Unit test: spawn child, send `run_task`, assert `result` event arrives.

4. **Build `SubagentService`.** Manages multiple runners. Lifecycle (`spawn`, `cancel`, `shutdown_all`). Wire into `RuntimeContext`.

5. **Add the `spawn_subagent` tool.** Registered only on the orchestrator's tool registry. Routes calls to `SubagentService.spawn(...)`. Result event becomes the tool-call return value.

6. **Build the auto-flush evaluator and `process_pending_context()`.** Wire the right-of-way contract: defer while input non-empty, dispatch when empty.

7. **Expand the TUI status state to per-agent.** Replace `status_text: str` with a structured `dict[task_id, state]` or `StatusBoard`. Update the status renderer.

8. **Bump the TUI executor.** Allow N concurrent in-flight workers.

9. **Add streaming events.** `status`, `transcript`, `tool_call` per task — one at a time, with end-to-end tests for each.

10. **Verification.** End-to-end test: orchestrator spawns sub-agent via `spawn_subagent` tool call, child runs, parent receives result, parent's next LLM call sees the tool result.

## Relationship to the docs

- Use this file as the historical narrative and current-state audit.
- Use `PLAN_SUBAGENT.md` as the implementation-aligned design document.
- Use `CHECKLIST_SUBAGENT.md` as the work tracker for what is complete and what is still outstanding.

## Summary

The sub-agent topology has moved from a vague design idea to a concrete, half-built feature whose underlying scaffolding is mostly in place:

- The TUI, event model, turn coordinator, status state machine, tool framework, and compaction subsystem all support sub-agent integration as designed.
- The IPC transport, subprocess lifecycle, tool registration, auto-flush interaction, and multi-agent UI state are the remaining work.
- The single hardest blocker (event-queue mid-turn drain) is also the smallest change.
- The TUI is well-positioned (~60% built) for the orchestrator + sub-agent target; the remaining 40% is the IPC layer plus the auto-flush and multi-state UI evolution.

This roadmap exists to preserve that history while keeping future work grounded in what the code actually does today.
