# CHECKLIST_MONITOR_COMPACTION_AUDIT

Scope: compaction subsystem in `src/monitor/` (procedural codebase, not the OOP rewrite). See `PLAN_MONITOR_COMPACTION_AUDIT.md` for narrative.

## Completed
- [x] Remove destructive pre-summary truncation from `append_conversation_history`; replace with full-history-then-truncated-copy two-stage attempt.
- [x] Fix `generate_conversation_summary` cap-drop: pass `max_tokens` alongside `max_completion_tokens`; validate returned summary length post-call.
- [x] Add atomic build-then-swap + auto-truncate fallback to `reset_conversation_with_summary` via `_truncate_summary_to_fit` and `_build_truncated_history_copy`.
- [x] **Item #1** — Gate `check_limits` secondary triggers behind `SECONDARY_PRESSURE_RATIO = 0.5` (`history.py:812-828`).
- [x] **Item #2** — Pre-validate `skip_summary` truncation against `MAX_TOKEN_COUNT`, iteratively drop oldest non-system messages, bail without mutating state when even the system prompt alone overflows (`history.py:264-345`).
- [x] Defer `from monitor.lib.history import ...` to function-local scope in `monitor.lib.redis_utils.prepare_model_input`.
- [x] Defer `from monitor.lib.history import adjust_history_size` to function-local scope in `monitor.lib.built_in_commands`.
- [x] Add `_ensure_secondary_pressure` test helper and two regression cases for "secondary trigger without token pressure does not summarize".
- [x] Update `test_prompt_count_stale_after_summarization` to put the system under secondary pressure.
- [x] Verify: `tests/monitor` 510 passed, 1 skipped after both fixes.

## Remaining
- [ ] **M1** — Tool-call orphaning in `skip_summary` truncation. Walk back from the cut boundary until the kept prefix begins outside a tool cluster.
- [ ] **M2** — Invalidate / decrement chain-aware token rate-limit caches on every committed compaction so the rate-limiter does not deny on stale estimates.
- [ ] **L1** — Centralize `prompt_count_since_summarization` reset into a single helper; remove the scattered call sites.
- [ ] **L2** — Resolve the residual `monitor.lib.llm_utils ↔ history` import cycle so history tests collect in isolation, not only in full-suite mode. Likely requires lifting shared types out of `llm_utils`.
- [ ] **L3** — Narrow broad `except Exception` blocks adjacent to compaction state mutations to specific exception classes; surface a typed result instead of `logger.error(...)`.

## Test Hygiene
- [x] All compaction tests exercise only the public interface (`check_limits`, `append_conversation_history`, `reset_conversation_with_summary`); no `_`-prefixed access.
- [x] Constraint: if a test requires a public API to be *added* for it to pass, the test should not exist.

## Notes
- This checklist is intentionally separate from `CHECKLIST_COMPACTION_FIX.md`, which tracked the OOP rewrite. That checklist is closed; this one is open.
