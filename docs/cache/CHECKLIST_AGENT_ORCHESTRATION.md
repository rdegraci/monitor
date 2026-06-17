# Checklist: Agent Orchestration (src/monitor/)

Working validation checklist for the current orchestration stack. This refresh
replaces the older implementation checklist shape with a state-of-the-world
checklist aligned to what is actually present in `src/monitor/` today.

Use `[x]` for complete and `[ ]` for incomplete.

## 0. Core availability
- [x] `agent_create` exists.
- [x] `agent_send` exists.
- [x] `agent_gather` exists.
- [x] `agent_kill` exists.
- [x] `agent_list` exists.
- [x] `agent_logfile` exists.
- [x] Orchestration is gated by `MONITOR_ENABLE_AGENT_ORCHESTRATION`.
- [x] Orchestration is UNIX-oriented (`screen` + AF_UNIX design center).

## 1. Spawn path
- [x] `agent_create(...)` launches a real `monitor --agent` child.
- [x] Child receives `MONITOR_AGENT_SOCKET`.
- [x] Child receives `MONITOR_AGENT_ID`.
- [x] Child receives recursion-depth metadata.
- [x] Child startup initializes reporting via `agent_reporter.from_env()`.
- [x] Spawned child can emit frames back to the parent orchestrator.

## 2. Frame protocol and transport
- [x] A dedicated frame protocol module exists.
- [x] A dedicated AF_UNIX listener module exists.
- [x] A dedicated child reporter module exists.
- [x] The child emits `hello` / `status` / `stdout` / `result` / `error` /
      `exit` / `heartbeat` frames.
- [x] The protocol is versioned and length-prefixed.
- [ ] Re-audit stale-socket and socket-path-limit behavior in runtime docs.

## 3. Orchestrator registry and state ownership
- [x] The orchestrator owns a lock-guarded registry of agent state.
- [x] Per-agent terminal state is tracked.
- [x] Dirty disconnect state is tracked.
- [x] Result payloads are retained.
- [x] Pending human-visible output is buffered.
- [x] Pending next-turn injections are buffered.
- [x] Spawn accounting exists for breadth and total caps.

## 4. Interactive visibility
- [x] Active agent status can render in a prompt toolbar.
- [x] Agent output can be drained above the prompt.
- [x] TUI mode has its own output draining path.
- [x] Normal prompting degrades cleanly when no agents are active.
- [ ] Validate operator clarity under heavier multi-agent output load.

## 5. Async fire-and-continue model
- [x] `agent_create(...)` returns immediately rather than blocking.
- [x] Background agent terminal notices can be queued for a later turn.
- [x] Main-thread folding into `config.enqueue_next_llm_prefix(...)` exists.
- [x] `agent_gather(...)` exists as the explicit blocking wait path.
- [ ] Add stronger docs on when gather should and should not be used.

## 6. Failure honesty
- [x] `agent_gather(...)` returns `ok` / `failed` / `pending` buckets.
- [x] Dirty disconnects surface as failure.
- [x] Error frames surface as failure.
- [x] Never-connected timed-out agents surface as failure.
- [x] Timeout is represented as pending, not success.
- [x] Clean terminal result is represented as success.
- [ ] Improve operator-facing recovery guidance after partial failure.

## 7. Lifecycle controls
- [x] One-shot sub-agents are the default.
- [x] Persistent sub-agents are opt-in.
- [x] `agent_send(...)` exists for follow-up prompts.
- [x] `agent_kill(...)` exists for explicit cleanup.
- [x] Heartbeats exist.
- [x] Heartbeat timeout handling exists.
- [x] Idle timeout exists for persistent agents.
- [x] Idle reaping exists.
- [ ] Expand test coverage for persistent follow-up workflows.

## 8. Safety bounds
- [x] Recursion depth is bounded.
- [x] Concurrent breadth is bounded.
- [x] Total spawned agents per session is bounded.
- [x] Conservative defaults are in place.
- [ ] Re-check whether hello-time depth enforcement should be added as defense
      in depth even though spawn-time depth enforcement already exists.

## 9. Delegated write policy
- [x] Sub-agent write policy exists.
- [x] `SUBAGENT_WRITE_ACCESS=none` is supported.
- [x] `SUBAGENT_WRITE_ACCESS=delegated` is supported.
- [x] `SUBAGENT_WRITE_ACCESS=full` is supported.
- [x] Delegated mode requires explicit grant metadata.
- [x] Delegated mode supports write scope restriction.
- [x] Write enforcement happens in `--agent` mode.
- [ ] Make researcher-vs-worker policy more explicit in user-facing guidance.

## 10. Compatibility expectations
- [x] Screen remains the PTY substrate.
- [x] Logfile-based inspection remains available.
- [x] Backend orchestration remains isolated from the synchronous core request
      path.
- [x] Adjacent cache docs have been refreshed to reduce drift from current
      behavior.

## 11. Recommended next validations
- [ ] Add a concise operator guide for bounded orchestration usage.
- [ ] Add benchmark scenarios for parallel audit and partial failure handling.
- [ ] Add more persistent-agent follow-up tests.
- [ ] Tighten async completion notice formatting and length discipline.
- [ ] Improve operator-visible summaries for active and recently completed work.

## Bottom line
- [x] The codebase has a real orchestrator/child architecture.
- [x] Delegation is asynchronous and bounded.
- [x] Failures are surfaced honestly.
- [x] Lifecycle and write controls exist.
- [ ] The main remaining work is documentation polish, stronger validation, and
      richer long-horizon ergonomics rather than basic orchestration existence.
