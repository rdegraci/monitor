# CHECKLIST_SUBAGENT

## Goal
Track the work needed to build the orchestrator + sub-agent topology in `monitor_oop`: a primary instance launches additional `monitor_oop` instances as sub-agents via subprocess + JSON Lines IPC and integrates their results back into its own conversation as tool-call returns.

This tracker is the companion to:
- `docs/cache/PLAN_SUBAGENT.md` (design)
- `docs/cache/ROADMAP_SUBAGENT.md` (narrative + current-state audit)

## Scope
This tracker covers:
- the IPC transport (subprocess + JSON Lines over stdin/stdout)
- the `--agent` entry mode
- `SubagentRunner` and `SubagentService` infrastructure
- the `spawn_subagent` tool
- the auto-flush interaction model (user-right-of-way contract)
- TUI evolution to support concurrent sub-agents (mid-turn drain, multi-worker, per-agent status)
- end-to-end verification through realistic sub-agent dispatch scenarios

## Milestone 1: TUI Scaffolding
- [x] Choose `src/monitor_oop/core/presentation/` as the home for TUI code.
- [x] Build the three-pane prompt_toolkit `Application` (output / status / input).
- [x] Add a worker `ThreadPoolExecutor` so turn execution is off the UI thread.
- [x] Build the transcript pipeline (buffer + renderer + viewport) with tail-follow.
- [x] Render assistant transcript blocks with STX/ETX markers and syntax highlighting; subagent/error blocks rendered plain.
- [x] Suppress runtime TUI logging during interactive execution.
- [x] Quiet TUI bootstrap in `build_app`.

## Milestone 2: Event Model
- [x] Define typed event dataclasses: `UserTranscriptEvent`, `AssistantTranscriptEvent`, `ErrorTranscriptEvent`, `SubagentTranscriptEvent`, `StatusEvent`, `BackgroundCompletionEvent`, `SubagentResultEvent`, `ErrorEvent`, `InputDraftEvent`, `OutputEvent`.
- [x] Add `task_id` correlation fields where relevant.
- [x] Add `failure_kind` to `TurnCompletionResult` and `BackgroundCompletionEvent` for distinct transient-vs-fatal rendering (currently `"rate_limited"` is the only recognized non-default value; sub-agent failures will use additional values).
- [x] Wire `_route_presentation_event` to dispatch each event type to the appropriate state update.
- [ ] **BLOCKER:** Drain the event queue on every redraw tick (currently drains only on `BackgroundCompletionEvent`). Without this, mid-turn sub-agent events sit invisibly in the queue until the parent's own turn completes.

## Milestone 3: TurnCoordinator
- [x] Build `TurnCoordinator` with `begin_turn`, `add_internal_context`, `add_subagent_result`, `add_background_event`, `mark_background_complete`, `snapshot`, `clear_turn`.
- [x] Define `InternalContextEntry` record shape: `id`, `source`, `kind`, `text`, `timestamp`, optional `metadata`.
- [x] Expose snapshot fields: `turn_id`, `background_status`, `has_pending_work`, `internal_context_entries`, `subagent_results`, `background_events`, `request_context_ready`.
- [x] Provide the public `set_pending_work` API so tests can drive pending-work state without poking private attributes.

## Milestone 4: Mid-Turn UI Feedback
- [x] Add `RuntimeContext.status_listener` callback (optional; `None` for CLI/server paths).
- [x] `TuiApp` registers itself as listener on construction; listener mutates `status_text` directly and calls `application.invalidate()` to bypass the (non-mid-turn-draining) event queue.
- [x] Status state machine with color coding: `idle` (green), `working` / `compacting` / `rate limited (idle)` (yellow), `completed (idle)` (green), `failed (idle)` (red).
- [x] Compaction emits `compacting` → restores `working` via `try/finally` so the indicator never sticks.

## Milestone 5: Cross-Process-Ready Diagnostics
- [x] Establish typed-exception pattern with `RateLimitDeniedError` (fields: `reason`, `model`, `current`, `limit`, `retry_after_seconds`; `__str__` for human display).
- [x] REPL surfaces structured exceptions to stdout, loop continues.
- [x] TUI surfaces structured exceptions via `failure_kind` on `TurnCompletionResult`/`BackgroundCompletionEvent` for distinct status rendering.

## Milestone 6: Tool-Call Cluster Preservation (Load-Bearing for Sub-Agent Result Integration)
- [x] `ConversationBoundaryTracker.preserved_tail` keeps complete assistant + tool-call + tool-result clusters together across compaction.
- [x] `LLMRequestBuilder.build_input` emits `tool_calls`, `tool_call_id`, and `name` fields on each request message when present (previously stripped, which broke tool-call continuity across compaction).
- [x] Compaction tests verify tool-call clusters survive and the request layer carries them end-to-end.

## Milestone 7: `--agent` Entry Mode
- [ ] Add `--agent` flag to `__main__.py` alongside `--tui` and default REPL.
- [ ] In `--agent` mode, read JSON commands from stdin line-by-line.
- [ ] In `--agent` mode, dispatch each command via the existing `ConversationSession` and `LLMService`.
- [ ] In `--agent` mode, write JSON events to stdout one object per line.
- [ ] In `--agent` mode, route `RuntimeContext.status_listener` to emit `{"event": "status", ...}` lines to stdout.
- [ ] Audit `print()` calls in the codebase; redirect `sys.stdout` to `sys.stderr` for child processes in `--agent` mode as a defense against stray output corrupting the event stream.
- [ ] Add a unit test: spawn the child via `python -m monitor_oop --agent`, send one `run_task`, assert one `result` event back.

## Milestone 8: `SubagentRunner` (IPC Layer)
- [ ] Implement `SubagentRunner` in `core/infrastructure/`.
- [ ] Spawn the child with `subprocess.Popen([sys.executable, "-m", "monitor_oop", "--agent"], stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True, bufsize=1, env=os.environ.copy())`.
- [ ] Daemon reader thread parses stdout line-by-line, invokes an `on_event` callback per JSON object.
- [ ] `on_event` callback translates each JSON event to a matching TUI event and enqueues it on `TuiApp.event_queue`.
- [ ] `send(command_dict)` serializes and writes with `\n` framing + flush.
- [ ] `shutdown(timeout=5)` sends `{"cmd": "shutdown"}`, waits, kills if non-responsive.
- [ ] EOF handling: emit `exited` event with the subprocess exit code.
- [ ] Stderr handling: optional tee to a per-task log file for forensics.

## Milestone 9: `SubagentService` (Lifecycle Management)
- [ ] Implement `SubagentService` in `core/infrastructure/`.
- [ ] `spawn(prompt) -> task_id` creates a `SubagentRunner` and dispatches one task.
- [ ] `cancel(task_id)` routes a cancel command to the owning runner.
- [ ] `shutdown_all()` cleanly shuts down all runners on TUI exit.
- [ ] Track lifecycle state per runner (PID, started_at, last_event_at, exit_code).
- [ ] Wire into `RuntimeContext` like other infrastructure services.
- [ ] Handle subprocess spawn failure (immediate Popen exception) by emitting `error` + `exited` for the task.

## Milestone 10: LLM-Driven Dispatch
- [ ] Register `spawn_subagent(task: str)` tool on the orchestrator's tool registry only.
- [ ] Tool handler routes calls to `SubagentService.spawn(...)`.
- [ ] Tool handler registers a result callback so the eventual sub-agent `result` event becomes the tool-call return value.
- [ ] Recursion depth control: `MONITOR_AGENT_DEPTH` env var, decremented per spawn, children refuse to spawn at 0.
- [ ] Children's tool registry excludes `spawn_subagent` unless `MONITOR_AGENT_DEPTH > 0` is explicitly set.

## Milestone 11: Sub-Agent Result Integration
- [ ] When a child's `result` event arrives, wrap it as a `tool`-role `Message` with the matching `tool_call_id` (from the spawning tool call).
- [ ] Insert the wrapped message into `internal_context_entries` on the parent's `TurnCoordinator`.
- [ ] Verify the boundary tracker preserves the spawning-tool-call + sub-agent-result cluster across compaction.
- [ ] Verify the parent LLM sees the sub-agent's result as a normal tool return value.

## Milestone 12: Auto-Flush Interaction Model
- [ ] Implement an auto-flush evaluator: runs on every event-queue drain plus a periodic safety-net timer.
- [ ] Conditions for auto-flush: `input_draft is empty` AND `internal_context_entries non-empty` AND no active turn.
- [ ] Add a `process_pending_context()` method on `ConversationSession` that flushes pending entries to the LLM with no new user message (uses the `previous_response_id` chain).
- [ ] Modify `process_user_input` to drain `internal_context_entries` into the request *before* the user's message (chronological order).
- [ ] Debounce auto-flush ~300 ms (tunable) after the last result arrives.
- [ ] Add a visible `[N queued]` indicator in the status line when results are pending.
- [ ] Verify right-of-way contract: pending results never auto-dispatch while the user is composing.

## Milestone 13: Concurrent Sub-Agent Support
- [ ] Replace the single-string `TuiApp.status_text` with per-agent state (`dict[task_id, state]` or `StatusBoard` object).
- [ ] Update the status-line renderer to display either individual per-agent state or an aggregate count (decision: see Open Questions in `PLAN_SUBAGENT.md`).
- [ ] Bump the `TuiApp` `ThreadPoolExecutor` from `max_workers=1` to a configurable N.
- [ ] Verify multiple in-flight sub-agents update their respective UI state correctly without races.

## Milestone 14: Verification
- [ ] Unit test: spawn `--agent` child via Python, send one `run_task`, assert one `result` event arrives.
- [ ] Unit test: `SubagentRunner` cleanly shuts down on `shutdown` command; falls back to kill on timeout.
- [ ] Unit test: child crash (non-zero exit) emits `error` + `exited` events with the exit code.
- [ ] Unit test: malformed JSON on the child's stdout is logged and skipped without crashing the parent reader thread.
- [ ] Integration test: orchestrator's tool registry has `spawn_subagent`; child's does not.
- [ ] Integration test: `MONITOR_AGENT_DEPTH=0` child cannot spawn further sub-agents.
- [ ] Integration test: auto-flush fires when input field is empty and results are pending; defers while input has draft text.
- [ ] Integration test: user-submit drains pending `internal_context_entries` into the request ahead of the user's message.
- [ ] End-to-end test: parent receives `spawn_subagent` tool call from LLM → spawns child → child completes → parent's next LLM call sees the result as a `tool`-role message with matching `tool_call_id`.
- [ ] End-to-end test: tool-call cluster (parent's spawn + sub-agent's result) survives a compaction event in the parent's history.
- [ ] All tests use only the public interface (no `_`-prefixed access).

## Notes
- Start with one in-flight sub-agent. Concurrent sub-agents are Milestone 13; don't gate the first milestone on them.
- The event-queue mid-turn drain (Milestone 2 final item) is the single biggest unlock — fix it first, even before `--agent` mode.
- Sub-agent dispatch is a tool call from the orchestrator LLM's perspective. No special LLM-side grammar.
- Sub-agent results enter the parent's history as `tool`-role messages tied to the spawning tool call's `tool_call_id`. Compaction safety relies on the cluster preservation from Milestone 6.
- The IPC is stable: same Python module on both sides, JSON-serializable events, no external dependencies.
- If queue-and-wait rate-limiting semantics become important for sub-agents, build a `RateLimitedScheduler` layer wrapping `RateLimitService` rather than expanding the gate itself (see `PLAN_RATE_LIMITING.md`).
