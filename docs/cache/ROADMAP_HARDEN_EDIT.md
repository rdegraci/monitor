# Roadmap: Harden the Edit Engine

Phased delivery plan derived from `PLAN_HARDEN_EDIT.md` and
`CHECKLIST_HARDEN_EDIT.md`. Targets the `modify_source_code` / ProtocolEngine
whole-file regeneration fallback in `src/monitor/lib/protocol_engine.py`.

> **Sequencing:** comes AFTER the deterministic bulk-replace tool, which already
> built the shared verification gate (`edit_verification.py`). This work reuses
> that gate. (See the sequencing note in `PLAN_HARDEN_EDIT.md`.)

---

## Phase 0 — Foundations
**Goal:** Confirm reuse points before touching the engine.
- [done] `edit_verification.verify_file_content` exists (three tiers).
- [done] `_assemble_and_save` is the single write chokepoint; on success it is
  called twice (finalize + return-value) → the gate must be idempotent and
  raise on failure.
**Exit:** Integration points confirmed.
**Risk:** Low.

## Phase 1 — Verification gate (keystone)
**Goal:** Tier-2 never silently writes broken code.
- Run the gate inside `_assemble_and_save` before the write; raise
  `EditVerificationError` on failure; write a `.rejected` sidecar; remove the
  checkpoint; catch at the `modify_source_code` entrypoint and return a clean
  descriptive message.
**Exit:** A regeneration that breaks Python/JSON is rejected unwritten, original
intact, model told why.
**Risk:** Medium — touches the assembly/return flow; mitigated by raising at the
single chokepoint.

## Phase 2 — Collateral-change guard
**Goal:** Surface (and warn on) unintended rewrites.
- Footprint vs original (added/removed lines, hunks); log every edit; warn on
  large footprint; include summary in the result.
**Exit:** Every tier-2 edit logs a footprint; oversized rewrites warn.
**Risk:** Low.

## Phase 3 — Syntax-aware chunk boundaries
**Goal:** Eliminate mid-construct chunk seams.
- `_make_chunk_plan` snaps boundaries to safe seams at bracket depth zero;
  `MAX_LINES_PER_CHUNK` stays the upper bound.
**Exit:** Boundaries land on safe seams; single-chunk files unchanged.
**Risk:** Low-Medium — boundary edge cases; covered by tests.

## Phase 4 — Reflection
**Goal:** A verification failure drives correction, not a blind write.
- Agent-level reflection (descriptive failure result) shipped in Phase 1.
- Inner-loop auto-correction deferred (fragile vs the existing
  global-retry/checkpoint machinery; revisit if agent-level proves insufficient).
**Exit:** Model receives an actionable rejection it can react to.
**Risk:** Low (agent-level); High (inner-loop, hence deferred).

## Phase 5 — Adversarial test corpus
**Goal:** Lock the guarantees.
- Reject-broken-Python / reject-broken-JSON / freeform-writes / footprint /
  boundary-snapping / single-chunk-unchanged / sidecar+checkpoint-removal.
**Exit:** Suite green; regressions locked.
**Risk:** Low.

## Phase 6 — Instrumentation
**Goal:** Visibility into tier-2 usage.
- Count + log `modify_source_code` invocations. Full surgical-vs-fuzzy analytics
  deferred.
**Exit:** Each invocation is counted/logged.
**Risk:** Low.

---

## Dependency graph
```
P0 ─► P1 ─► P2 ─► P3 ─► P5
       │           ▲      ▲
       └─ P4 ──────┘      │
       (agent-level)      │
   P6 (independent) ──────┘
```
P1 is the keystone (reuses the gate built by the bulk-replace effort). P2/P3 are
independent hardenings; P5 tests all of it.

## Highest-risk items
1. **P1 gate integration** — must raise at the single chokepoint so checkpoint
   removal / double-call don't write broken code; sidecar preserves content.
2. **P3 boundary correctness** — never cut inside an unbalanced block.

## Out of scope (deferred)
- Inner-loop LLM auto-correction (agent-level reflection covers the need).
- Full tier-1-vs-tier-2 usage analytics / prompt-steering tuning.
- True semantic (type-check / test) verification — the gate is parse/structure
  level only.
