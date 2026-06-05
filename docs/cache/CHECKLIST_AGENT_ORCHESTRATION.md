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
> emitted hello → status → exit.
>
> **Phase 3 + most of Phase 4 also done.** `agent_orchestrator` gained a bounded
> pending-output buffer + `drain_pending_output`/`render_toolbar`/
> `has_active_agents`; `conversation.py` `get_input` now routes through
> `_prompt_with_agent_bridge`, which flushes agent output above the prompt and
> shows a live `bottom_toolbar` — ONLY when agents are active (byte-identical to
> a plain prompt otherwise; degrades on any error). Full suite 1337 passed / 1
> skipped.
>
> NOT yet done: Phase 4 live-flush DURING a prompt (currently flushes between
> prompts; toolbar refreshes live), Phase 5 (dirty-disconnect → history
> rollback; detection exists, firing the rollback is unwired), Phase 6 (depth
> ceiling at `hello`, direct-children-only toolbar), Phase 7 (hardening), Phase 8
> (LLM `agent_gather` layer). The legacy child-served status-socket + poller path
> was left intact (additive); cleanup deferred.

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
- [x] Clean path: terminal frame (result/error/exit) → close → recorded as not
      dirty (`AgentListener` + orchestrator registry).
- [x] Dirty disconnect: close WITHOUT a terminal frame → `dirty` (listener), AND
      **heartbeat-lapse** (Phase 5) — a hung or never-connected agent is marked
      dirty by `_heartbeat_monitor` after `MONITOR_AGENT_HEARTBEAT_TIMEOUT`
      (default 45s). Reaping also releases the spawn reservation. 3 tests.
- [x] Failure surfaced to the LLM via `agent_gather`'s `failed` bucket (this is
      how the orchestrator "rolls back" — it sees the failure as tool-result
      data and reacts). A hidden auto-rollback of the orchestrator's own history
      is unnecessary given gather's honesty, and was deliberately NOT added.
- [ ] (If ever needed) per-turn history checkpoint/rollback on the *sub-agent*
      side — deferred; a crashed sub-agent is gone, so this has no clear payoff.

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
> **Model = ASYNC fire-and-continue** (decision 2026-06-04): spawning returns
> instantly, the human keeps working, results flow back later — into the LLM's
> NEXT turn and to the human live. Blocking gather is a demoted escape hatch.
> Maps to PLAN Part 3 (async-reframed).

### 11a. Async result harvest (keystone — NOT YET BUILT)
- [x] `agent_create`/`agent_send`/`agent_list`/`agent_kill`/`agent_logfile`
      registered as LLM-callable; `agent_create` returns immediately with
      `session_name`.
- [x] `agent_gather(agent_ids, timeout)` built + 9 tests — **but now DEMOTED**
      to the explicit "wait for these now" escape hatch, NOT the default path.
- [ ] **Async injection (the keystone):** on a terminal `result`/`error` frame,
      enqueue a notice into the orchestrator's NEXT turn via
      `config.enqueue_next_llm_prefix(...)` (`[background agent <id> finished:
      <summary>]` / `... FAILED: <reason>`), deduped/delivered-once. The turn
      ENDS after `agent_create`; the human keeps working.
- [ ] (Optional) non-blocking `agent_poll(ids?)` tool — returns terminal-so-far
      results on demand; never blocks.
- [ ] Live-flush-during-prompt so the human SEES background progress (see §5 /
      Phase 4 — re-elevated).

### 11b. Structured summaries (context-budget protection)
- [x] Sub-agents emit their per-turn assistant response as a `result` frame
      (`conversation._maybe_report_agent_result` → `agent_reporter.active()`),
      reachable by `agent_gather`. Reporter singleton: `agent_reporter.set_active`/
      `active`; wired in `app.py`. End-to-end tested (8b→8a). 6 tests.
- [ ] `--agent`-mode system prompt instructs "return a tight, structured
      summary" so the captured response stays concise (prompt-side, pending).

### 11c. Breadth & cost caps (not just depth)
- [x] Sibling/breadth cap on concurrent subagents (`MONITOR_AGENT_MAX_BREADTH`,
      **safe default 1**) — `agent_create` refuses past it via `orch.can_spawn`.
- [x] Total-agent cap per session (`MONITOR_AGENT_MAX_TOTAL`, **safe default 1**;
      0 disables). Counters are leak-proof: never-connected spawns are reaped by
      the heartbeat monitor, releasing their reservation. All caps follow
      code-default → config.yaml → env precedence. 4 tests + config-override tests.
- [ ] Aggregate child *token*-costs up to the orchestrator — deferred (the
      breadth/total caps bound runaway fan-out; token accounting is a separate
      cost-tracker extension).

### 11d. Partial-failure honesty  — DONE
- [x] `agent_gather` buckets EVERY requested id into ok / failed / pending;
      never silently drops (crash → failed, error → failed, never-connected →
      failed, timeout → pending). Tested.
- [x] A crashed child surfaces as `failed` with a "dirty disconnect" reason
      (history-rollback wiring itself is Phase 5).

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
- [ ] Teach the **fire-and-continue** pattern: spawn and KEEP GOING; the result
      arrives on a later turn. Do NOT block on `agent_gather` unless you truly
      cannot proceed without the result. Remain the sole file writer.

### 11h. Tests
- [x] `agent_gather` aggregates results / buckets partial failures (9 tests) —
      still valid for the escape-hatch path.
- [ ] **Async injection**: a completed background agent's result is enqueued to
      the next turn (and a failed one surfaces as FAILED), deduped.
- [ ] `agent_poll` returns terminal-so-far without blocking (if built).
- [ ] Breadth/total caps enforced (over-spawn rejected) — done (§11c tests).
- [ ] Live-flush: background output streams above the prompt without corrupting
      the input line; chatty agent is coalesced/capped.
- [ ] Follow-up via `agent_send` reaches a live subagent and updates its state.
