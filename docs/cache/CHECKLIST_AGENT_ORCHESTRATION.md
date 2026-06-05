# Checklist: Agent Orchestration (src/monitor/)

Build-order task list derived from `PLAN_AGENT_ORCHESTRATION.md`. Check items
as completed. Items are ordered so each builds on verified prior work.
`[x]` marks behavior that **already exists** in the codebase today.

> A subagent = an instance of the app launched in `--agent` mode. The spawn
> path (`:agent create` → `agent_create` → `create_interactive_subagent`) is
> already ~90% wired; see §1b for the two concrete gaps that make it real.

> **IMPLEMENTED (2026-06-04) — Phases 1, 2, 0.5 done, verified end-to-end.**
> New modules (stdlib-only, no config dependency → import-cycle-safe):
> - `lib/agent_protocol.py` — Phase 1 frame protocol (length-prefixed, versioned,
>   typed; partial-read-tolerant `FrameDecoder`). 16 tests.
> - `lib/agent_listener.py` — Phase 2 orchestrator AF_UNIX listener (accept/reader
>   threads, pluggable `on_frame` sink, clean-vs-dirty disconnect, teardown). 7 tests.
> - `lib/agent_reporter.py` — Phase 0.5 child reporting client (`hello/status/
>   stdout/result/error/exit/heartbeat`, monotonic seq, heartbeat thread,
>   degrades to no-op if no orchestrator). 8 tests.
> - `lib/agent_orchestrator.py` — Phase 0.5 orchestrator singleton (listener +
>   lock-guarded frame registry = seed of the Phase 3 shared state). 5 tests.
>
> Live wiring: `screen_handler.py` spawns `python -m monitor --agent` and passes
> `MONITOR_AGENT_SOCKET` (orchestrator listener) + `MONITOR_AGENT_ID`; `app.py`
> startup calls `agent_reporter.from_env()` (heartbeat + status + atexit exit).
> **Verified with a real subprocess**: a spawned `monitor --agent` connected and
> emitted hello → status → exit. Full suite 1332 passed / 1 skipped.
>
> NOT yet done: Phase 3 (bridge into the live prompt_toolkit loop), Phase 4 (UI),
> Phase 5 (rollback), Phase 6 (index/depth at `hello`), Phase 7 (hardening),
> Phase 8 (LLM `agent_gather` layer). The legacy child-served status-socket +
> poller path was left intact (additive); cleanup deferred.

## 0. Pre-flight
- [x] `MONITOR_ENABLE_AGENT_ORCHESTRATION`, `MONITOR_AGENT_DEPTH`,
      `MONITOR_AGENT_MAX_DEPTH` plumbing exists in `config.py` (env + YAML).
- [x] Depth propagation already happens at spawn
      (`MONITOR_AGENT_DEPTH=<curr+1>`, ceiling-checked — `screen_handler.py`).
- [x] Per-session socket path already created (`<name>.sock`).
- [ ] Decide socket directory + naming, verify it stays under the ~104-byte
      `sun_path` limit (current paths live under the meta dir).
- [x] UNIX-only guard (`is_platform_unix()` / `screen` presence) already gates
      the spawn path; document that orchestration is UNIX-only.

## 1b. Make `:agent create` spawn a real `--agent` subagent (THE net-new wiring)
- [ ] **Spawn side:** add `--agent` to `self.monitor_cmd`
      (`screen_handler.py:75`) so the child runs in agent mode (currently
      `["python", "-m", "monitor"]` with no flag).
- [ ] **Spawn side:** pass the socket path to the child, e.g.
      `MONITOR_AGENT_SOCKET=<name>.sock` in the same `env` list that already
      carries the depth vars (`screen_handler.py:364`).
- [ ] **Child side:** in the `config.AGENT` startup path (`app.py:354`, today a
      near-noop), connect to `MONITOR_AGENT_SOCKET` and emit framed
      `hello`/`status`/`stdout`/`result` frames — reuse the existing AF_UNIX
      client idiom at `screen_handler.py:667`.
- [ ] Verify a spawned child reports frames the orchestrator receives (smoke
      test before building the full bridge).

## 1. Frame protocol — wire layer
- [ ] Implement length-prefixed framing: `uint32` BE length + JSON body.
- [ ] Enforce ~1 MiB max frame size; reject oversize as protocol error.
- [ ] Define the envelope (`v`, `type`, `agent_id`, `seq`, `ts`, `body`).
- [ ] Reject mismatched protocol `v` loudly.
- [ ] Implement frame (de)serialization with partial-read reassembly
      (read until full length is available).

## 2. Frame protocol — semantics
- [ ] Implement `hello` (register + depth check against `MONITOR_AGENT_MAX_DEPTH`).
- [ ] Implement `status` (coalescing — latest `seq` wins).
- [ ] Implement `stdout` (ordered by `seq`).
- [ ] Implement `result` (exactly-one terminal success).
- [ ] Implement `error` (structured failure).
- [ ] Implement `exit` (clean shutdown notice).
- [ ] Implement `heartbeat` (liveness; define interval + timeout).
- [ ] Implement `cancel` (orch→child cooperative cancel).

## 3. Socket transport
- [x] AF_UNIX `SOCK_STREAM` client idiom already exists
      (`screen_handler.py:667,862`) — currently just pokes `b'\n'`; reuse it.
- [ ] AF_UNIX `SOCK_STREAM` **listener** (one per orchestrator).
- [ ] Set socket dir `0700`, socket file `0600`.
- [ ] (Optional) Verify peer uid via `SO_PEERCRED` / `LOCAL_PEERCRED` on accept.
- [ ] Stale-socket cleanup on startup and on crash (unlink before bind).
- [ ] Clean teardown: close listener, join threads, unlink socket on exit.

## 4. Thread → prompt_toolkit bridge (blocking-`.prompt()` model)
> NOTE: `get_input` uses synchronous `session.prompt()` (`conversation.py:473`),
> NOT `app.run_async()`. There is no persistent loop — use lock-guarded shared
> state, not `call_soon_threadsafe`/`asyncio.Queue`.
- [x] prompt_toolkit is already the input layer (`PromptSession`, lexer,
      keybindings — `core/conversation.py`); no main-loop rewrite needed.
- [ ] Accept thread (listens, spawns per-connection reader threads).
- [ ] Reader threads parse frames and update **lock-guarded shared state**
      (status map + bounded pending-output queue); they never print directly.
- [ ] Single lock guards the status map + pending-output queue + connection list.
- [ ] Bounded pending-output queue; drop-and-count `status` on full; never drop
      `result`/`error`/`exit`.
- [ ] Frames arriving between prompts buffer and flush before the next prompt.

## 5. Terminal UI
- [ ] `bottom_toolbar` callable reads the lock-guarded status map;
      `get_app().invalidate()` (guarded no-op when no app is live).
- [ ] `stdout`/`result` blocks flushed via `run_in_terminal` under an active
      `patch_stdout()` during a prompt; printed before next prompt when idle.
- [ ] Wrap `session.prompt()` in `patch_stdout()` so background output is safe.
- [ ] Verify prompt input buffer is never touched by a reader thread.

## 6. Lifecycle & failure handling
- [ ] Clean path: `result`/`error` → `exit` → close → record outcome, no rollback.
- [ ] Dirty disconnect (close w/o `exit`, OR heartbeat lapse) → fire
      conversation-history rollback for the agent's correlation id.
- [ ] UI + docs state explicitly: rollback = conversation-history, NOT filesystem.

## 7. Index & registry
- [ ] Registry keyed by stable `agent_id`.
- [ ] `:agent <n>` numeric index resolved to `agent_id` at parse time against a
      snapshot; never stored.
- [ ] Verify kill cannot re-point a stale index.

## 8. Depth & nesting
- [x] `MONITOR_AGENT_DEPTH=<curr+1>` already propagated to children via env on
      spawn, and creation is blocked at the ceiling (`SubagentCreationBlocked`
      when depth ≥ `MONITOR_AGENT_MAX_DEPTH` — `screen_handler.py`).
- [ ] Also enforce the depth ceiling at `hello` (defense in depth on the socket).
- [ ] Confirm toolbar shows only DIRECT children (nested agents have their own
      orchestrator/listener).

## 9. Compatibility & regression guards
- [ ] Keep screen as PTY substrate; `:agent attach` still works.
- [ ] Keep logfiles; `:agent logs` / `logfile` still work.
- [ ] Legacy `screen -dm` + `stuff` path remains as non-participating tier.
- [ ] Backend stays synchronous (no async creep into file tools / token
      trackers / history loaders).

## 10. Tests
- [ ] Framing round-trip incl. partial reads and oversize rejection.
- [ ] Each frame type's handler.
- [ ] Disconnect-without-exit triggers rollback.
- [ ] Heartbeat-lapse triggers rollback.
- [ ] Status coalescing under queue pressure.
- [ ] Index resolution stable across a kill.
- [ ] Depth ceiling enforced.

## 11. LLM orchestration layer (roadmap Phase 8 — the capstone)
> Turns the subsystem from "spawns processes" into "an LLM that orchestrates."
> The frames already feed the human terminal (§4/§5); this routes them into the
> orchestrator LLM's context as tool results. Maps to PLAN Part 3.

### 11a. Result-return-into-context channel (keystone)
- [x] `agent_create`/`agent_send`/`agent_list`/`agent_kill`/`agent_logfile`
      already registered as LLM-callable (`tool_definitions.py:~682-749`).
- [ ] `agent_create(prompt)` returns an `agent_id` immediately (fire; no block).
- [ ] Add **blocking** `agent_gather(ids, timeout)` → returns collected
      `result`-frame payloads as ONE tool result (spawn-N-then-gather).
- [ ] Gather blocks until all listed agents hit a terminal frame
      (`result`/`error`/`exit`), or quorum/timeout.
- [ ] Add a result-retrieval tool returning `result`-frame **payloads**
      (current `agent_logfile` returns a path — useless for LLM aggregation).

### 11b. Structured summaries (context-budget protection)
- [ ] Subagents return concise structured findings via the `result` `summary`
      field — never raw transcripts.
- [ ] `--agent`-mode system prompt instructs: "your final `result` is data for
      an orchestrator; return a tight, structured summary."

### 11c. Breadth & cost caps (not just depth)
- [ ] Sibling/breadth cap on concurrent subagents.
- [ ] Total-agent / token budget across the run.
- [ ] Aggregate child token-costs up to the orchestrator (extend cost trackers).

### 11d. Partial-failure honesty
- [ ] `agent_gather` reports terminal state for EVERY requested id
      (e.g. `{ok: [...], failed: [{id, reason}]}`); never silently drops.
- [ ] A crashed child's rollback stays local; orchestrator still gets a
      structured "failed/missing" entry.

### 11e. Orchestrator as sole file writer
- [ ] Researcher subagents are read-only (safe to fan out wide).
- [ ] Worker subagents do NOT write the working tree directly; they return
      proposed changes.
- [ ] Primary orchestrator applies all writes serially (single writer of record).

### 11f. Follow-up prompts & lifecycle
- [ ] `agent_send` follow-up semantics defined (queue vs interrupt while busy).
- [ ] Idle-reaping policy so subagents don't pile up.

### 11g. System-prompt orchestration guidance
- [ ] Replace "create subagents as necessary" with explicit when-to-fan-out
      criteria (independent/parallelizable, broad search, isolation needed) vs.
      do-it-inline.
- [ ] Model is cost/latency-aware; crisp tool descriptions; recommend
      spawn-N-then-gather.

### 11h. Tests
- [ ] `agent_gather` returns aggregated results in-context for N subagents.
- [ ] Partial failure surfaced (kill one mid-run → reported, not dropped).
- [ ] Breadth cap + token budget enforced (over-spawn rejected).
- [ ] Sole-writer policy: worker proposals applied serially, no tree conflicts.
- [ ] Follow-up via `agent_send` reaches a live subagent and updates its state.
