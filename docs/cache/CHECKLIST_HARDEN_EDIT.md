# Checklist: Harden the Edit Engine

Build-order task list derived from `PLAN_HARDEN_EDIT.md`. Targets
`src/monitor/lib/protocol_engine.py` (the `modify_source_code` / ProtocolEngine
whole-file regeneration fallback). `[x]` marks done.

> Sequencing: this comes AFTER the deterministic bulk-replace tool, which built
> the shared verification gate (`src/monitor/lib/edit_verification.py`). This
> work REUSES that gate — no fork.

> **IMPLEMENTED (2026-06-04).** All parts built and tested in
> `src/monitor/lib/protocol_engine.py`:
> - Part 1 gate: `_guard_and_verify` inside `_assemble_and_save` raises
>   `EditVerificationError` (writes `<source>.rejected`, removes checkpoint,
>   target untouched), reusing `edit_verification.verify_file_content`.
> - Part 2 guard: `_collateral_footprint` logs +/- lines & hunks, warns on
>   large footprint, includes the summary in the success result.
> - Part 3 boundaries: `_make_chunk_plan` + `_safe_chunk_boundary` snap to safe
>   seams (blank line / top-level, depth-0), `MAX_LINES_PER_CHUNK` upper bound,
>   fallback to fixed cut.
> - Part 4 reflection: agent-level — `modify_source_code` converts
>   `EditVerificationError` into an actionable message. Inner-loop auto-correct
>   remains deferred.
> - Part 6 instrumentation: `_MODIFY_SOURCE_CODE_CALLS` counter + log.
> - Tests: `tests/monitor/lib/test_protocol_engine_hardening.py` — 11 tests;
>   full lib suite 891 passed / 1 skipped, no regressions.
> - Assembly de-duped via `_assemble_full_script` (shared by full + partial
>   saves). Partial saves intentionally bypass the gate (failure sidecar).

## 0. Pre-flight
- [x] Shared verification gate exists: `edit_verification.verify_file_content`
      (three tiers: code / structured / freeform; degrades to skip).
- [x] Single chokepoint identified: all write paths route through
      `_assemble_and_save` before `_atomic_write_text` (`protocol_engine.py`).
- [x] Note the double-call: on success `_assemble_and_save` runs at the
      finalize site AND again to produce the return value — gate must be
      idempotent and raise (not silently return) on failure.

## 1. Post-assembly verification gate (Part 1 — keystone)
- [ ] Reuse `verify_file_content(path, content)` inside `_assemble_and_save`,
      after assembly and BEFORE `_atomic_write_text`.
- [ ] On failure: do NOT write the target; raise a typed
      `EditVerificationError` carrying (path, tier, error, rejected-sidecar).
- [ ] Write the rejected content to a `<source>.rejected` sidecar so it isn't
      lost.
- [ ] Remove the checkpoint on rejection (avoid a poisoned resume that
      re-rejects the same chunks).
- [ ] Invariant: a tier-2 edit either writes a file that passes its validator,
      or writes nothing to the target and reports why.

## 2. Collateral-change guard (Part 2)
- [ ] Compute a change footprint vs the original
      (`self._modification_script_content`): lines added/removed, hunk count.
- [ ] Log the footprint summary on every tier-2 edit (no silent truncation).
- [ ] Warn (do NOT hard-block) when the footprint is large relative to the
      original (heuristic threshold) — surfaces "rewrote half the file".
- [ ] Include the footprint summary in the success result string.

## 3. Syntax-aware chunk boundaries (Part 3)
- [ ] Rewrite `_make_chunk_plan` to snap each boundary to a safe seam
      (blank line / top-level def-class) at bracket depth zero.
- [ ] Keep `MAX_LINES_PER_CHUNK` as the upper bound — only move the cut
      EARLIER, never later.
- [ ] Never split inside an unbalanced block; fall back to the fixed cut if no
      safe seam is found in the lookback window.
- [ ] Single-chunk files (the common case) are unaffected.

## 4. Reflection on verification failure (Part 4)
- [ ] Agent-level reflection: return a descriptive failure result (syntax error
      + "not applied" + sidecar path) so the calling model can react (retry,
      switch to a surgical edit, refine the request).
- [ ] (Deferred) Inner-loop auto-correction: feed the validator error back into
      the ProtocolEngine for a bounded re-generation. Documented as future work
      — the existing global-retry/checkpoint machinery makes this fragile to
      wire safely; agent-level reflection covers the need for now.

## 5. Adversarial test corpus (Part 5)
- [ ] Verification gate rejects broken Python (no write; original intact).
- [ ] Verification gate rejects broken structured text (JSON).
- [ ] Freeform text assembles + writes without a gate.
- [ ] Collateral footprint computed and reported.
- [ ] `_make_chunk_plan` snaps to safe seams (boundary on blank line, not
      mid-construct) with a small `lines_per_chunk`.
- [ ] Single-chunk plan unchanged for small files.
- [ ] `.rejected` sidecar written on rejection; checkpoint removed.

## 6. Bias toward tier 1 (Part 6 — instrumentation)
- [ ] Count + log each `modify_source_code` invocation (visibility into how
      often the risky path runs).
- [ ] (Deferred) Full comparison vs surgical-tool usage / prompt-steering
      tuning — documented as future analytics work.

## Preserved (do not regress)
- [ ] Atomic write + checkpoint/resume intact (gate sits in FRONT of the write).
- [ ] Never hard-block on an unknown language / missing toolchain → logged skip.
- [ ] Backend stays synchronous.
