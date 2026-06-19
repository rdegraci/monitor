# SPEC: Smart Orchestration (role models, phase escalation, cost telemetry)

Behavior contracts for making orchestration **model-aware** and **cost-honest**.
Builds on the substrate in `PLAN_AGENT_ORCHESTRATION.md` (frame protocol,
listener, registry, async harvest). Three independent capabilities:

1. Role-based model selection
2. Phase-scoped model escalation (orchestrator)
3. Sub-agent cost telemetry → orchestrator fuel/status aggregation

Locked decisions: **telemetry cadence = result-only**; **payload = `cost_usd` +
`total_tokens`** (no composition/effort fields in v1).

---

## 1. Role-based model selection

New config keys, each falling back to `MODEL` / `REASONING_EFFORT` when unset
(same pattern as `ADV_REASONING_MODEL` / `COMMIT_MODEL`):

| Key | Applies to | Scope |
|---|---|---|
| `SUBAGENT_MODEL` / `SUBAGENT_REASONING_EFFORT` | `monitor --agent` children | Whole-session |
| `ORCHESTRATOR_MODEL` / `ORCHESTRATOR_REASONING_EFFORT` | coordinator synthesis turns | Phase-scoped only |

**Startup contract (`apply_role_model_override`):**
- `config.AGENT` true → switch the session to `SUBAGENT_*`.
- otherwise → **no startup override**. Orchestrator and standalone sessions keep base `MODEL` / `REASONING_EFFORT` at startup.
- The orchestrator uses `ORCHESTRATOR_*` *transiently per collation turn* — see §2 — so it "backs down to MODEL" between coordination turns rather than running the strong model all session.

**Sub-agent whole-session override:**
- The override sets the **session-owning** model and **must re-derive** `MODEL_CONTEXT_WINDOW` / `MODEL_OUTPUT_WINDOW` / `MODEL_MAX_TPM` — done via `set_model`, which accepts a full model string directly.
- **Dated model names required** — an unresolvable name is logged and left on base `MODEL` (no crash; `set_model` returns False).
- Unset keys → no behavior change (plain `MODEL`).
- An explicit CLI `--model` wins over the role override.

## 2. Phase-scoped model escalation (orchestrator)

A **collation/synthesis turn** is the deterministic trigger: the LLM call that folds gathered sub-agent results into the next assistant response. Only that turn runs on `ORCHESTRATOR_MODEL`.

The orchestrator runs `MODEL` by default and swaps to `ORCHESTRATOR_MODEL` **transiently, per call**, only on collation/synthesis turns — then falls back automatically (no `set_model`; same mechanism as the `ADV_REASONING_MODEL` swap).

**Triggers (priority order in `resolve_turn_model`):**
1. collation/synthesis turn → `ORCHESTRATOR_MODEL`
2. reasoning override active → `ADV_REASONING_MODEL`
3. else → `MODEL`

**Contract:**
- **Collation/synthesis** is the only phase-scoped trigger: the folding call runs on `ORCHESTRATOR_MODEL` and is attributed to that model in `SESSION_CALIBRATION_BY_MODEL`.
- **Decomposition/spawning** has no a-priori trigger (the spawn decision emerges from the call); it relies on the existing reasoning-bump heuristic.
- The swap is per-call `kwargs` only — never `set_model` (which would reset session state).
- **Cache caveat:** the prompt cache is keyed per model; each swap forfeits the cached-input discount for that call. Acceptable for hard spawn/collate turns — the swap must **not** fire on routine turns.

## 3. Sub-agent cost telemetry → fuel/status aggregation

Today a `--agent` child reports a `result` (`ok` + `summary`) and exits; its cost
never reaches the orchestrator, so F: and U:/T: understate true session spend.

**Frame contract (v1, result-only):**
- The `result` frame body gains an optional `usage` block:
  `{ "model": <str>, "cost_usd": <float>, "total_tokens": <int> }`.
- Values are the **delta since the child's previous `result`** (so persistent
  multi-task agents don't double-count). One-shot agents report their whole run.
- Telemetry is **best-effort**: a missing/malformed `usage` block is ignored;
  it never affects the agent's success/failure classification.

**Orchestrator aggregation contract:**
- The reader thread must **not** mutate `config` cost globals directly (it races
  the main thread). It accumulates pending usage in the **lock-guarded registry**
  (`agent_orchestrator.py`), keyed per agent.
- The **main thread** folds pending agent usage during the existing
  `drain_pending_injections` step into:
  - `SESSION_COST_USD` and `SESSION_TOTAL_TOKENS` (status-line U:/T:), and
  - `SESSION_CALIBRATION_BY_MODEL[<usage.model>]` `cost_usd` + `total_tokens`
    (F: sizing and `:fuel_debug` per-model rate for `SUBAGENT_MODEL`).
- Net effect: F: drains for orchestrator **and** agent spend (true session
  budget); `:fuel_debug` in the orchestrator can calibrate the sub-agent model
  from real fleet usage.

**Out of scope for v1** (deferred): token composition (cached/uncached/output)
and effort-weighted accumulators in the payload; heartbeat-piggybacked live
drain. v1 is result-only, cost+tokens.

---

## Non-goals
- No per-swap compaction ratio (history is shared/sized for the primary; see
  `PLAN_AGENT_ORCHESTRATION.md` and the per-model `AUTO_COMPACT_THRESHOLD_RATIO`).
- No change to the spawn/lifecycle/caps model.
