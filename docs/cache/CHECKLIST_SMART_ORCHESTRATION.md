# CHECKLIST: Smart Orchestration

Tracks `PLAN_SMART_ORCHESTRATION.md`. `[ ]` todo · `[~]` in progress · `[x]` done.

**Status:** Stage 1 implemented (tests green, 1450 passed); commit pending.
Stages 2–3 not started.

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

## Stage 2 — Sub-agent cost telemetry (result-only, cost+tokens)
- [ ] `agent_protocol.result(...)` accepts optional `usage`; `_validate` tolerant
      (drop malformed, never reject frame)
- [ ] `agent_reporter.result(...)` sends `usage`; child computes delta since last
      result from `SESSION_COST_USD` / `SESSION_TOTAL_TOKENS`
- [ ] `conversation.py:536` emit passes `usage={model, cost_usd, total_tokens}`
- [ ] registry (`agent_orchestrator.py`) accumulates pending per-agent usage
      (lock-guarded)
- [ ] main-thread drain folds usage into `SESSION_COST_USD`,
      `SESSION_TOTAL_TOKENS`, `SESSION_CALIBRATION_BY_MODEL[usage.model]`
- [ ] tests: emit delta on result; malformed ignored; fold updates all three
      once; persistent-agent two-result no double-count
- [ ] manual: spawn an agent, confirm orchestrator F: / U:/T: move by the agent's
      spend; `:fuel_debug` shows the `SUBAGENT_MODEL` bucket
- [ ] full suite green; commit

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
