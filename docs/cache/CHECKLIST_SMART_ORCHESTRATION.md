# CHECKLIST: Smart Orchestration

Tracks `PLAN_SMART_ORCHESTRATION.md`. `[ ]` todo · `[~]` in progress · `[x]` done.

**Status:** Stages 1–3 implemented (tests green, 1473 passed); commit pending.
Stage 3 reconciled Stage 1 — orchestrator behavior is now phase-scoped, not
whole-session (only `--agent` children take a whole-session `SUBAGENT_MODEL`).

## Stage 1 — Role-based model selection ✅ (commit pending)
- [x] config globals: `ORCHESTRATOR_MODEL`, `ORCHESTRATOR_REASONING_EFFORT`,
      `SUBAGENT_MODEL`, `SUBAGENT_REASONING_EFFORT` (default None) + global decl
- [x] loader reads the four keys
- [x] `apply_role_model_override()` helper (sub-agent whole-session override only;
      no startup override for orchestrator). NOTE: no reverse-map needed —
      `set_model` accepts a full model string directly and returns False on an
      unknown name.
- [x] call it in `app.py` after the `--agent` flag, before
      `configure_subsystems()`, gated on no explicit `--model`
- [x] `config.yaml.example`: commented keys + dated-name note + cost caveat
- [x] tests (`test_role_model_override.py`, 8): role resolution, agent precedence,
      no-role no-op, unset-model-applies-effort, model==active skip,
      unresolvable-model-keeps-base, invalid-effort-ignored
- [x] full suite green (1450 passed, 1 skipped)
- [ ] commit Stage 1
- [ ] (deferred) live `monitor --agent` spawn confirming a child picks up
      `SUBAGENT_MODEL` end-to-end — unit-tested via `set_model` spy only

## Stage 2 — Sub-agent cost telemetry (result-only, cost+tokens) ✅ (commit pending)
- [x] `agent_protocol`: `sanitize_usage()` + `result(..., usage=)` carries a
      sanitized `{model, cost_usd, total_tokens}` block. NOTE: usage is sanitized
      at build + on read, not in `_validate` (envelope validation unchanged).
- [x] `agent_reporter.result(...)` sends `usage`; reporter holds the
      `reported_cost_usd`/`reported_total_tokens` cursor (config-free)
- [x] child emit (`conversation.py`) computes the delta from `SESSION_COST_USD` /
      `SESSION_TOTAL_TOKENS` and passes `usage`
- [x] registry (`agent_orchestrator._pending_usage`) accumulates usage from
      RESULT frames (lock-guarded, reader thread); `drain_pending_usage()`
- [x] main-thread fold (`_fold_agent_injections_into_prefixes` →
      `config.record_agent_usage`) updates `SESSION_COST_USD`,
      `SESSION_TOTAL_TOKENS`, `SESSION_CALIBRATION_BY_MODEL[model]`
- [x] tests (`test_agent_cost_telemetry.py`, 10): sanitize valid/reject; result
      includes/drops usage; on_frame queue+drain; malformed-on-read ignored;
      record folds + accumulates two results; malformed/zero ignored
- [x] full suite green (1460 passed)
- [ ] commit Stage 2
- [ ] (deferred) manual live spawn: confirm orchestrator F: / U:/T: move by the
      agent's spend and `:fuel_debug` shows the sub-agent model bucket — the
      child-emit→fold glue is covered by units, not an end-to-end spawn

## Stage 3 — Phase-scoped escalation ✅ (commit pending)
- [x] reconcile Stage 1: removed orchestrator startup override (orchestrator now
      phase-scoped, not whole-session)
- [x] `CURRENT_TURN_IS_COLLATION` flag: reset at top of `prepare_query_context`,
      set True in `_fold_agent_injections_into_prefixes` when notices fold in
- [x] `resolve_turn_model(...)` priority resolver (collation→ORCH; override→ADV;
      else MODEL), kept pure + reasoning-capable gate
- [x] `effective_turn_effort(...)` — override/steady, floored to
      `ORCHESTRATOR_REASONING_EFFORT` on collation (avoids an inert key)
- [x] `llm_utils` swap site consumes collation + orchestrator (swap fires on
      collation OR override; ADV output cap only on ADV swaps)
- [x] `token_management` attribution mirrors model + effort resolution
- [x] SPEC §1/§2 contradiction fixed (sub-agent whole-session; orchestrator
      phase-scoped)
- [x] tests (`test_phase_escalation.py`, 11): resolver priority + gates,
      effort floor/no-downgrade, fold sets/clears the flag
- [x] full suite green (1473 passed)
- [ ] commit Stage 3
- [ ] (deferred) live spawn: confirm a real collation turn runs ORCHESTRATOR_MODEL
      and non-collation turns run MODEL

## Cross-cutting verification
- [ ] dated model names resolve in `model_config.json` for any model used as
      `ORCHESTRATOR_MODEL` / `SUBAGENT_MODEL`
- [ ] no cross-thread mutation of `config` cost globals from the listener reader
      thread (audit)
- [ ] swap fires only on collation/hard turns, not routine turns (cache cost)
- [ ] distill stable outcomes into `docs/` per `docs/cache/README.md`
