# CHECKLIST: Smart Orchestration

Tracks `PLAN_SMART_ORCHESTRATION.md`. `[ ]` todo · `[~]` in progress · `[x]` done.

**Status:** Stages 1–2 implemented (tests green, 1460 passed); commit pending.
Stage 3 not started.

## Stage 1 — Role-based model selection ✅ (commit pending)
- [x] config globals: `ORCHESTRATOR_MODEL`, `ORCHESTRATOR_REASONING_EFFORT`,
      `SUBAGENT_MODEL`, `SUBAGENT_REASONING_EFFORT` (default None) + global decl
- [x] loader reads the four keys
- [x] `apply_role_model_override()` helper (role resolution + `set_model` + role
      reasoning effort). NOTE: no reverse-map needed — `set_model` accepts a full
      model string directly and returns False on an unknown name.
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

## Stage 3 — Phase-scoped escalation
- [ ] read `conversation._fold_agent_injections_into_prefixes` + synthesis call
      path; pick the phase signal (per-call arg vs short-lived flag)
- [ ] extend `resolve_turn_model(...)` to priority resolver (phase → ORCH; override
      → ADV; else MODEL), kept pure
- [ ] set the collation phase signal at the synthesis call site
- [ ] `llm_utils` swap site + `token_management` attribution consume the resolver
- [ ] tests: collation → orchestrator model; non-collation → MODEL; attribution
      bucket correct
- [ ] full suite green; commit

## Cross-cutting verification
- [ ] dated model names resolve in `model_config.json` for any model used as
      `ORCHESTRATOR_MODEL` / `SUBAGENT_MODEL`
- [ ] no cross-thread mutation of `config` cost globals from the listener reader
      thread (audit)
- [ ] swap fires only on collation/hard turns, not routine turns (cache cost)
- [ ] distill stable outcomes into `docs/` per `docs/cache/README.md`
