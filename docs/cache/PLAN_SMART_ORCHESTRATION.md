# PLAN: Smart Orchestration

Implementation approach and sequencing for `SPEC_SMART_ORCHESTRATION.md`. This is
the "smart" layer on top of the orchestration substrate in
`PLAN_AGENT_ORCHESTRATION.md`.

Three independent stages, each its own commit + tests. Build order: role models →
cost telemetry → phase escalation. (Telemetry is the load-bearing piece — it's
what makes the role split cost-honest — so it lands before the escalation that
relies on it being accurate.)

**Status:** Stages 1–2 implemented (tests green); commit pending. Stage 3 not
started. See `CHECKLIST_SMART_ORCHESTRATION.md`.

## Resolved risks (verified against the code)

- **Startup ordering.** `load_environment_globals()` derives MODEL/windows/TPM at
  `app.py:289`, but `config.AGENT` (from `--agent`) is set at `app.py:359`,
  *after* the loader. So the role override **cannot** live in the loader; it goes
  **after line 359, before `configure_subsystems()` (364)** — reverse-map the
  dated model → shorthand → `set_model(shorthand)`. `set_model`'s reset side
  effects (clears history, zeroes counters) are **no-ops at startup**, so this is
  safe. This also confirms the phase-swap must use a per-call `kwargs` override,
  not `set_model`.
- **Listener thread-safety.** `agent_listener.py` is transport-only: one reader
  thread per connection → pluggable `on_frame` sink; "the sink does its own
  locking." So agent cost must accumulate in the lock-guarded registry
  (`agent_orchestrator.py`) and be folded into `config` cost globals by the
  **main thread** during `drain_pending_injections` — never mutated from the
  reader thread.

## Stage 1 — Role-based model selection ✅ DONE (commit pending)

Self-contained; no protocol changes.

- `config.py`: add `ORCHESTRATOR_MODEL` / `ORCHESTRATOR_REASONING_EFFORT` /
  `SUBAGENT_MODEL` / `SUBAGENT_REASONING_EFFORT` globals (default None), loader
  reads, global decl.
- New helper (config.py): `apply_role_model_override()` — resolves role
  (`config.AGENT` → subagent; else `MONITOR_ENABLE_AGENT_ORCHESTRATION` →
  orchestrator; else none), then calls `set_model(role_model)` and sets the
  role's `REASONING_EFFORT`. Model and effort overrides apply independently;
  no-op when both are unset.
  - **Implementation note:** `set_model` accepts a **full model string**
    directly (no `get_model_reverse_mapping` needed) and returns False on an
    unknown name, so an unresolvable override is logged and left on base `MODEL`.
- `app.py`: call `apply_role_model_override()` after the `--agent` flag, before
  `configure_subsystems()`, **gated on no explicit `--model`** (CLI override
  wins).
- `config.yaml.example`: documented (commented) keys, dated-name note, cost caveat.
- Tests (`test_role_model_override.py`): role resolution, agent precedence,
  no-role no-op, unset-model-applies-effort, model==active skip,
  unresolvable-model-keeps-base, invalid-effort-ignored.

## Stage 2 — Sub-agent cost telemetry (result-only, cost+tokens) ✅ DONE (commit pending)

- `agent_protocol.py`: extend `result(...)` to accept an optional `usage` dict;
  validate shape in `_validate` (best-effort — drop malformed, never reject the
  frame).
- `agent_reporter.py`: `result(...)` gains `usage`; child computes the delta
  since its previous result from `SESSION_COST_USD` / `SESSION_TOTAL_TOKENS`.
- `conversation.py:536` (child result emit): pass `usage={model, cost_usd,
  total_tokens}`.
- `agent_orchestrator.py`: registry accumulates pending per-agent usage
  (lock-guarded); expose it on the drain path.
- main-thread drain (alongside `drain_pending_injections` /
  `_fold_agent_injections_into_prefixes`): fold pending usage into
  `SESSION_COST_USD`, `SESSION_TOTAL_TOKENS`, and
  `SESSION_CALIBRATION_BY_MODEL[usage.model]`.
- Tests: child emits usage delta on result; malformed usage ignored; orchestrator
  fold updates all three targets exactly once (no double-count across two
  results from a persistent agent).

## Stage 3 — Phase-scoped escalation

- `llm_model_utils.resolve_turn_model(...)`: extend to a priority resolver —
  phase=collation → `ORCHESTRATOR_MODEL`; reasoning override → `ADV_REASONING_MODEL`;
  else `MODEL`. Keep it pure; pass the phase in (read at the call site +
  token_management).
- Set a per-call "collation" phase signal where gathered results are folded into
  the next turn (`conversation._fold_agent_injections_into_prefixes` → the
  synthesis LLM call). (Read this path first to pick the cleanest signal —
  per-call arg vs a short-lived flag cleared after the call.)
- `llm_utils` swap site + `token_management` attribution both consume the
  extended resolver, so the synthesis call runs on — and is billed to —
  `ORCHESTRATOR_MODEL`.
- Decomposition: no dedicated trigger; relies on the bump heuristic.
- Tests: collation phase → orchestrator model; non-collation → MODEL; attribution
  lands in the orchestrator-model bucket; cache caveat documented (no test).

## Locked decisions
- Telemetry: **result-only**, payload **`cost_usd` + `total_tokens`** (+ `model`).
- Composition/effort payload and heartbeat live-drain: **deferred**.
- Naming: `SUBAGENT_*` (matches existing `SUBAGENT_MEMORY_SERVICES` /
  `SUBAGENT_WRITE_ACCESS`); `ORCHESTRATOR_*`; `_REASONING_EFFORT` suffix to match
  `REASONING_EFFORT` / `COMMIT_REASONING_EFFORT`.

## Open reads before each stage
- Stage 2/3: `agent_listener._reader_loop` sink wiring, `agent_orchestrator`
  registry + `drain_pending_injections`, `conversation._fold_agent_injections_into_prefixes`.
