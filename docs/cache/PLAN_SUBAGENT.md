# PLAN_SUBAGENT

## Goal
Add an orchestrator topology where the primary `monitor_oop` instance launches additional `monitor_oop` instances as sub-agents and integrates their results back into its own conversation. The first milestone supports one in-flight sub-agent; the architecture supports concurrent sub-agents from day one — initial scope keeps the surface small.

## Core Idea
A sub-agent **is another instance of the same app**, spawned as a separate OS process and communicating with the parent via subprocess + JSON Lines over stdin/stdout. The parent treats each completed sub-agent's payload as a `tool`-role message tied to the tool call that spawned it. Sub-agent text never rewrites user input.

## Design Principles
- Process-isolated sub-agents (OS-enforced crash blast radius = one subprocess).
- Explicit communication via structured JSON events; no shared mutable state.
- User's visible prompt stays honest — sub-agent results never silently rewrite user text.
- Sub-agent results enter the LLM context as `tool`-role messages tied to the spawning tool call.
- The TUI stays responsive while sub-agents run (worker thread + invalidate-on-event redraw).
- Start with one in-flight sub-agent; the architecture and lifecycle support concurrent later.

## IPC Transport
The chosen transport is **subprocess + JSON Lines over stdin/stdout**, with stderr reserved for diagnostic logs.

### Why
- Lightest weight; fits "sub-agent IS another instance of the same app" exactly.
- Same Python module on both sides → shared schema, no protocol drift.
- OS-enforced process isolation.
- Cross-platform (stdin/stdout/stderr work on Windows and POSIX).
- Easy to debug: pipe a JSON command in by hand, see what comes out.
- No external dependencies (Redis, gRPC, sockets) for a same-host parent/child relationship.

### Wire protocol

**Commands (parent → child, written to child stdin, one JSON object per line):**

```json
{"cmd": "run_task", "task_id": "uuid", "prompt": "...", "max_turns": 10}
{"cmd": "cancel", "task_id": "uuid"}
{"cmd": "shutdown"}
```

**Events (child → parent, written to child stdout, one JSON object per line):**

```json
{"event": "started",    "task_id": "uuid"}
{"event": "status",     "task_id": "uuid", "text": "compacting"}
{"event": "transcript", "task_id": "uuid", "role": "assistant", "text": "..."}
{"event": "tool_call",  "task_id": "uuid", "tool": "weather", "args": {...}}
{"event": "result",     "task_id": "uuid", "success": true,  "text": "..."}
{"event": "error",      "task_id": "uuid", "kind": "rate_limited", "message": "..."}
{"event": "exited",     "task_id": "uuid", "exit_code": 0}
```

`task_id` is the orchestrator's correlation handle — the child echoes it on every event. Each event maps to an existing TUI event type (`SubagentResultEvent`, `SubagentTranscriptEvent`, `StatusEvent`, `ErrorEvent`).

### New `--agent` mode
Add a third mode alongside `--tui` and the default REPL in `__main__.py`. In `--agent` mode the app:
- Reads JSON commands from stdin line-by-line.
- Dispatches each via the existing `ConversationSession` and `LLMService`.
- Writes JSON events to stdout.
- Routes the existing `RuntimeContext.status_listener` to emit `{"event": "status", ...}` lines instead of TUI events.

### Parent-side architecture
A new `SubagentRunner` in `core/infrastructure/`:
- Spawns `subprocess.Popen([sys.executable, "-m", "monitor_oop", "--agent"], stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True, bufsize=1, env=os.environ.copy())`.
- A daemon reader thread reads stdout line-by-line, parses JSON, invokes an `on_event` callback that enqueues a matching event on the parent's `TuiApp.event_queue` (thread-safe `deque.append`).
- `send(command_dict)` serializes and writes to stdin with `\n` framing + flush.
- `shutdown(timeout=5)` sends `{"cmd": "shutdown"}`, waits, then kills if non-responsive.

A `SubagentService` (sits alongside `RateLimitService` in `infrastructure/`) manages multiple runners:
- `spawn(prompt) -> task_id`.
- `cancel(task_id)`.
- `shutdown_all()` (called by `TuiApp.stop`).

Wired into `RuntimeContext` like every other service.

## LLM-Driven Dispatch
A `spawn_subagent(task: str)` tool is registered on the orchestrator's tool registry only — children don't see it (unless explicitly enabled via `MONITOR_AGENT_DEPTH` env var, which decrements per spawn to prevent unbounded recursion). The orchestrator LLM emits a normal tool call; the tool handler routes it to `SubagentService.spawn(...)` and registers a callback so the eventual `result` event becomes the tool-call return value.

This means the parent LLM controls orchestration through the same interface it uses for any other tool — no special "agent grammar" the LLM has to learn.

## Integration with Parent History
When a child's `result` event arrives, wrap it as a `tool`-role message with the matching `tool_call_id` (the call that spawned the child). The wrapped message goes into `internal_context_entries` on the parent's `TurnCoordinator`, pending the next LLM call. The boundary tracker preserves these tool-call clusters across compaction (and `LLMRequestBuilder` now emits the structured fields end-to-end, so the cluster survives into the actual request payload).

## Auto-Flush Interaction Model (Orchestrator UX)
The orchestrator's UX has two modes, gated by whether the user is composing:

```
if input_field has draft text:
    do nothing — defer; wait for the user to submit
elif internal_context_entries is non-empty (and no LLM call in flight):
    auto-flush pending sub-agent results to the parent LLM
    surface the assistant response in the transcript
else:
    idle
```

**Right-of-way contract:** as long as the user has *any* text in the input, the orchestrator defers sending pending sub-agent results — it knows the user will compose them into the next turn. The moment the input is empty, the orchestrator may drive forward autonomously. On user submit, pending results are merged into the request ahead of the user's message (chronological order).

**Implementation pieces needed:**
- An auto-flush evaluator that runs on every event-queue drain (and as a periodic safety-net timer): if `input_draft is empty` AND `internal_context_entries non-empty` AND no active turn, fire the auto-flush.
- A `process_pending_context()` path in `ConversationSession` that flushes `internal_context_entries` to the LLM with no new user message (uses the `previous_response_id` chain).
- Modify `process_user_input` to drain `internal_context_entries` into the request before the user's message.
- Debounce: schedule the auto-flush ~200–500 ms after the *last* result arrives so a burst of nearly-simultaneous children gets batched into one call.
- Visible indicator in the status line: `[N queued]` when results are pending; user knows there's something waiting.

## Internal Context Records and `TurnCoordinator`
Internal context records carry `id`, `source`, `kind`, `text`, `timestamp`, and optional `metadata`. `TurnCoordinator` owns per-turn internal context, sub-agent results, background completion state, and request-assembly input via its snapshot interface (`begin_turn`, `add_internal_context`, `add_subagent_result`, `add_background_event`, `mark_background_complete`, `snapshot`, `clear_turn`). See `MONITOR_OOP_CLASS_MAP.md` for the full interface.

These records are mostly internal to request construction and coordination. The TUI may surface summaries via `SubagentTranscriptEvent`, but the raw records stay hidden from the user's visible draft.

## Sub-Agent Lifecycle Details
1. **One-shot model (initial):** spawn per task, child exits when task done. Pays Python startup cost (~150 ms) per task. Optimize to a long-running pool only if startup cost matters.
2. **API key inheritance** via `env=os.environ.copy()`. Children get `OPENAI_API_KEY` from the parent's environment.
3. **Recursion depth** via `MONITOR_AGENT_DEPTH` env var. Each spawn decrements; children refuse to spawn at 0. Prevents unbounded recursion.
4. **Cancellation** is cooperative: parent sends `{"cmd": "cancel", "task_id": "..."}`; child honors it between LLM rounds. Escalate to SIGTERM after timeout, SIGKILL if still hung.
5. **Crash handling:** reader thread sees stdout EOF, then `wait()` gives the exit code; emit `error` + `exited` and mark the task failed in `TurnCoordinator`.
6. **Output isolation:** children must not print anything to stdout outside the event protocol — any stray `print()` would corrupt the JSON stream. Audit print calls; in `--agent` mode, redirect `sys.stdout` to `sys.stderr` as a defensive measure.
7. **Backpressure:** pipe buffers (~64 KB on Linux) block writes when full — natural flow control; no special handling needed for normal event volumes.
8. **Clean shutdown** on parent exit: `TuiApp.stop()` calls `subagent_service.shutdown_all()` before returning. Reader threads are daemons so they don't block parent exit.

## TUI Prerequisites for Sub-Agents
The TUI is already largely built — see `TUI_PLAN.md` for the full status state machine (idle / working / compacting / completed (idle) / failed (idle) / rate limited (idle)) and event flow. The existing event types are pre-positioned to receive parsed JSON events from `SubagentRunner`.

**Two TUI gaps block the sub-agent feature today:**

1. **Event queue doesn't drain mid-turn.** Today the queue drains only when a `BackgroundCompletionEvent` triggers it. With multiple async sub-agents emitting events while the parent's own LLM call is running, those events sit in the queue until that completion fires. Fix: drain on every redraw tick (or on every `enqueue_event` call, via `application.invalidate()`).
2. **Single-worker `ThreadPoolExecutor`.** Hard-coded to one worker. Bump to N for concurrent sub-agents. Also: the TUI's `status_text` is single-stringed; with multiple sub-agents reporting status concurrently, this needs to become per-agent (a `dict[task_id, state]` or a `StatusBoard` object the status line renders).

## Concrete First Milestone
Implement just enough to verify the wire:

1. Add `--agent` mode that reads one `run_task` from stdin, processes it through the existing `ConversationSession`, and writes `{"event": "result", "task_id": ..., "text": "..."}` to stdout. No streaming, no status, no cancel.
2. Build `SubagentRunner` (~80 lines).
3. Drive it from a unit test: spawn a child with a fixed prompt, assert the result event arrives. No TUI, no `spawn_subagent` tool — just prove the pipe works.
4. Fix the event-queue drain to fire on every redraw tick (general dependency, unlocks everything else).
5. Add the `spawn_subagent` tool registered to the orchestrator's tool registry only.
6. Add the streaming events (`status`, `transcript`) one at a time.
7. Build the auto-flush evaluator and `process_pending_context()` path.

## Open Questions
- Should sub-agent `transcript` events be shown live in the parent's transcript while the child runs, or only surfaced on completion?
- How should the parent surface a "cancel sub-agent" affordance to the user — keybind, interactive command, or a tool call from the orchestrator LLM?
- When concurrent sub-agents are running, should the status line show individual per-agent state, an aggregate count, or both?
- Should the auto-flush debounce window be fixed (e.g., 300 ms) or tunable via config?

## Success Criteria
- The main chat loop remains responsive while a sub-agent runs.
- Each sub-agent runs as a separate `monitor_oop` process.
- The parent detects sub-agent completion without waiting for user input.
- Sub-agent results are injected into the parent LLM flow as `tool`-role messages with matching `tool_call_id` — boundary tracker preserves the cluster across compaction.
- The TUI cleanly separates Output, Status Line, and Input.
- The user's visible draft prompt remains honest and unchanged.
- The right-of-way contract holds: pending results never auto-dispatch while the user is composing.
- The system stays simple enough to test with one sub-agent first; concurrent sub-agents are a follow-on.

The TUI separation, status state machine, and turn coordination scaffolding are in place. The remaining work is the IPC layer, the `--agent` mode, the `spawn_subagent` tool, the event-queue drain fix, and the auto-flush evaluator.
