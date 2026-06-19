# Design Note: Sub-agent Frame Protocol, Terminal Bridge, and Async Harvest

> Scope: `src/monitor/` only. This is a working design note for the current
> orchestration architecture. Unlike the older draft, this version is aligned
> with the code that now exists in `src/monitor/`.

## Status summary

Agent orchestration is no longer speculative. The following core pieces exist:

- `src/monitor/lib/agent_protocol.py`
- `src/monitor/lib/agent_listener.py`
- `src/monitor/lib/agent_reporter.py`
- `src/monitor/lib/agent_orchestrator.py`
- `src/monitor/core/agent_tools.py`
- `src/monitor/lib/screen_handler.py`
- `src/monitor/core/conversation.py`

Sub-agents are real `monitor --agent` children running in detached GNU screen
sessions, reporting back to the parent orchestrator over an AF_UNIX socket.

## What a sub-agent is

A sub-agent is an instance of the monitor app launched in `--agent` mode.

Creation flow:
- `agent_create(...)`
- `ScreenHandler.create_interactive_subagent(...)`
- `python -m monitor --agent`
- child receives `MONITOR_AGENT_SOCKET`, `MONITOR_AGENT_ID`, depth metadata,
  lifecycle metadata, and optional delegated-write metadata
- child starts `agent_reporter.from_env()` and emits frames back to the parent

This makes orchestration real rather than cosmetic log scraping.

## Architectural decision: screen + AF_UNIX hybrid

The current architecture keeps:
- **screen** as the process and PTY substrate,
- **AF_UNIX** as the structured control and reporting channel.

This preserves:
- detach and attach behavior,
- logfiles,
- independent child process lifetime,
- structured result transport.

## Frame protocol

The implementation uses a length-prefixed framed protocol over AF_UNIX
`SOCK_STREAM`.

Each frame carries a versioned envelope including:
- `v`
- `type`
- `agent_id`
- `seq`
- `ts`
- `body`

The protocol supports at least these frame types:
- `hello`
- `status`
- `stdout`
- `result`
- `error`
- `exit`
- `heartbeat`
- `cancel`
- `usage` (proposed) — child cost/token telemetry; see
  "Cost telemetry and fuel aggregation".

Key implementation modules:
- `src/monitor/lib/agent_protocol.py`
- `src/monitor/lib/agent_listener.py`
- `src/monitor/lib/agent_reporter.py`

## Orchestrator state ownership

The orchestrator owns a lock-guarded shared registry in
`src/monitor/lib/agent_orchestrator.py`.

Tracked state includes:
- per-agent frame history,
- latest status,
- result payloads,
- error payloads,
- terminal state,
- dirty disconnect state,
- last-frame timestamps,
- last-activity timestamps,
- pending terminal output,
- pending next-turn injections,
- breadth and total spawn accounting.

This registry is the source of truth for:
- live toolbar status,
- pending prompt-adjacent output,
- `agent_gather(...)`,
- next-turn async completion injection,
- heartbeat timeout reaping,
- idle reaping of persistent agents.

## Terminal bridge

The interactive bridge is implemented for the codebase's actual synchronous
`session.prompt(...)` model.

Relevant path:
- `src/monitor/core/conversation.py` via `_prompt_with_agent_bridge(...)`

Behavior:
- when no agents are active, prompting is effectively plain prompt behavior,
- when agents are active, a bottom toolbar renders live status,
- buffered agent output is drained above the next prompt,
- prompt corruption is avoided by not allowing arbitrary reader-thread output
  to print directly into the live input flow.

The TUI path drains agent output separately in `src/monitor/tui/app.py`.

## Async result harvest

The orchestration model is **fire-and-continue by default**.

That means:
- `agent_create(...)` returns immediately,
- the main orchestrator keeps helping the user,
- terminal sub-agent outcomes are queued for later use,
- the next relevant orchestrator turn can receive background completion notices.

Implemented path:
- `agent_orchestrator.drain_pending_injections()`
- `conversation._fold_agent_injections_into_prefixes()`
- `config.enqueue_next_llm_prefix(...)`

This is a crucial architectural point: background results are consumed in two
ways:
1. surfaced to the human operator,
2. folded into the orchestrator's next LLM turn.

## Failure model

The failure model is based on honest terminal classification, not silent
assumption.

Current behaviors include:
- reported `error` frame -> failure,
- dirty disconnect -> failure,
- never-connected child that times out heartbeat -> failure,
- timeout during gather -> pending,
- clean terminal result -> success.

Relevant code paths:
- `src/monitor/lib/agent_orchestrator.py`
- `src/monitor/core/agent_tools.py`

Important clarification:
- failure handling is about **conversation and orchestration truthfulness**,
  not filesystem rollback.
- a delegated failure does **not** imply repo state rollback.

## Lifecycle policy

The lifecycle model now exists in code.

### One-shot by default
Sub-agents are one-shot by default.

Mechanism:
- spawner sets `MONITOR_AGENT_ONE_SHOT=1` unless `persistent=True`
- child reporter exposes `one_shot`
- conversation loop reports the result and exits when the one-shot task turn is
  complete

### Persistent opt-in
Persistent agents are explicit:
- `agent_create(..., persistent=True)`
- follow-up via `agent_send(...)`
- explicit cleanup via `agent_kill(...)`

### Safety net
Persistent agents are protected by:
- heartbeat monitoring,
- idle timeout,
- idle reaping.

## Spawn caps and bounded autonomy

Bounded autonomy is enforced in code.

Current default limits:
- `MONITOR_ENABLE_AGENT_ORCHESTRATION = False`
- `MONITOR_AGENT_MAX_DEPTH = 1`
- `MONITOR_AGENT_MAX_BREADTH = 1`
- `MONITOR_AGENT_MAX_TOTAL = 1`

This means the default system is conservative by design.

## Delegated write policy

Sub-agent write behavior is separately controlled from orchestration enablement.

Supported modes:
- `SUBAGENT_WRITE_ACCESS=none`
- `SUBAGENT_WRITE_ACCESS=delegated`
- `SUBAGENT_WRITE_ACCESS=full`

Delegated mode further requires:
- `MONITOR_SUBAGENT_WRITE_GRANTED=1`
- optional `MONITOR_SUBAGENT_WRITE_SCOPE`

Write enforcement happens in `src/monitor/core/tooling.py`.

This means the codebase now supports a real researcher vs worker distinction,
although the documentation and guidance around that distinction can still be
improved.

## Role-based model selection (proposed)

Different orchestration roles want different models. Planned config knobs, each
falling back to `MODEL` / `REASONING_EFFORT` when unset (same pattern as
`ADV_REASONING_MODEL` / `COMMIT_MODEL`):

- `ORCHESTRATOR_MODEL` / `ORCHESTRATOR_REASONING_EFFORT` — the coordinator.
- `SUBAGENT_MODEL` / `SUBAGENT_REASONING_EFFORT` — `--agent` children (groups
  with the existing `SUBAGENT_*` knobs).

A spawned child resolves `SUBAGENT_MODEL` at config load when `config.AGENT` is
set; the orchestrator resolves `ORCHESTRATOR_MODEL` when
`MONITOR_ENABLE_AGENT_ORCHESTRATION` is true and it is not itself an agent. Either
override must re-derive that model's context/output windows and TPM from
`model_config.json` (reverse-map → shorthand), so **dated model names are
required** (an undated name fails the reverse lookup → `MODEL_MAX_TPM` is
unresolved).

### Phase-scoped escalation (proposed)

Rather than running the orchestrator on the strong model for its whole session,
the strong model is swapped in **transiently, per call**, only for the
coordination-critical phases — then it falls back to `MODEL` automatically (no
`set_model`; the same mechanism as the `ADV_REASONING_MODEL` swap, so "back down"
is free):

- **Collation/synthesis** is a deterministic trigger: when agent results are
  folded into the next orchestrator turn
  (`_fold_agent_injections_into_prefixes`), that LLM call runs on
  `ORCHESTRATOR_MODEL`.
- **Decomposition/spawning** is not knowable a priori — the decision to spawn
  emerges from the call itself — so it leans on the existing reasoning-bump
  heuristic rather than a dedicated pre-call trigger.

Implementation: extend `resolve_turn_model(...)` to consider triggers in
priority order — orchestration phase → `ORCHESTRATOR_MODEL`; reasoning override →
`ADV_REASONING_MODEL`; else `MODEL` — so one resolver drives both the call site
(`llm_utils`) and cost attribution (`token_management`).

Cost note: the prompt cache is keyed per model, so each swap forfeits the
cached-input discount for that call. Acceptable for genuinely hard spawn/collate
turns; this is exactly why the phase-swap must **not** fire on routine turns.

## Cost telemetry and fuel aggregation (proposed)

Today a `--agent` child tracks its own cost in its own in-memory
`SESSION_CALIBRATION_BY_MODEL` / `SESSION_COST_USD`, reports a `result` summary
(`ok` + `summary` only), and exits — the dollars never reach the orchestrator. So
the orchestrator's F: fuel gauge and the U:/T: status-line costs **understate true
session spend**: the entire sub-agent fleet is invisible to the budget. This
matters more once `SUBAGENT_MODEL` exists, because moving work onto cheaper agents
would otherwise *hide* spend rather than account for it.

Planned fix — sub-agents report cost back, orchestrator aggregates:

- **Frame protocol:** add a `usage` frame (and/or a `usage` block on `result`)
  carrying the child's model, `cost_usd`, `total_tokens`, and — ideally — the
  token composition (cached / uncached / output) and effort-weighted multiplier
  accumulators, so the parent can populate a full per-model calibration entry,
  not just a cost total.
- **Cadence:** at least once per completed task (on `result`); optionally
  piggybacked on `heartbeat` for live F: drain during long agent runs.
- **No double counting:** report deltas since the previous frame, or report
  cumulative and let the orchestrator track per-agent last-seen (the registry
  already keys per-agent frame history by `seq`).
- **Orchestrator aggregation:** the listener folds child usage into the parent's
  `SESSION_COST_USD` + `SESSION_TOTAL_TOKENS` (status line U:/T:) and into
  `SESSION_CALIBRATION_BY_MODEL[SUBAGENT_MODEL]` (F: sizing and `:fuel_debug`
  per-model rate). F: then drains for orchestrator **and** agent spend — a true
  session budget — and `:fuel_debug` can calibrate the sub-agent model from real
  fleet usage.

This is the prerequisite that makes role-based models cost-honest.

## What is complete vs still evolving

### Implemented
- child `--agent` reporting path,
- AF_UNIX frame protocol,
- orchestrator listener and registry,
- live status tracking,
- prompt bridge,
- async next-turn injection,
- `agent_gather(...)`,
- breadth and total caps,
- one-shot and persistent lifecycle modes,
- heartbeat timeout handling,
- idle reaping,
- delegated-write enforcement.

### Still evolving
- more polished operator guidance,
- stronger persistent-agent follow-up coverage,
- richer structured result artifacts,
- clearer researcher-vs-worker user-facing docs,
- broader observability and benchmarking,
- optional worktree isolation if write-capable delegation expands,
- role-based model selection (`ORCHESTRATOR_MODEL` / `SUBAGENT_MODEL`) with
  phase-scoped escalation (proposed),
- sub-agent cost telemetry aggregated into the orchestrator's F: gauge and
  U:/T: status line (proposed).

## Relationship to long-horizon docs

This document is the orchestration-specific design note.

For the broader product-level view of planning, continuity, multi-step coding
behavior, and bounded autonomy, see:
- `docs/cache/SPEC_LONG_HORIZON.md`
- `docs/cache/PLAN_LONG_HORIZON.md`
- `docs/cache/ROADMAP_LONG_HORIZON.md`
- `docs/cache/CHECKLIST_LONG_HORIZON.md`

## Bottom line

Monitor now has a real orchestration substrate:
- structured child reporting,
- bounded asynchronous delegation,
- live operator visibility,
- next-turn result harvest,
- explicit lifecycle control,
- explicit delegated-write policy.

It should be understood as a bounded orchestrator architecture, not an
unconstrained autonomous multi-agent swarm.
