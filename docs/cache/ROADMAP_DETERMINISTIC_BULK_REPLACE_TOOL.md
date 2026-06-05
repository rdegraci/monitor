# Roadmap: Deterministic Bulk-Replace Tool

Phased delivery plan derived from `PLAN_DETERMINISTIC_BULK_REPLACE_TOOL.md` and
`CHECKLIST_DETERMINISTIC_BULK_REPLACE_TOOL.md`. Each phase ends at a
demonstrable, shippable state. Phases are sequential.

> Fills the empty middle cell of the edit space (single → **bulk** → fuzzy).
> Smaller and lower-risk than the orchestration or hardening work — it mostly
> *reuses* existing editor machinery. No `sed`, no generic shell-exec.

> **Relationship to other plans:** shares the verification gate with
> `PLAN_HARDEN_EDIT.md` (Part 5) and reduces load on `modify_source_code`. Best
> sequenced so the hardening plan's verification gate exists first (or build the
> gate here and let hardening reuse it).

## Sequencing decision: build THIS before hardening `modify_source_code`

**Default order: deterministic bulk-replace tool first, then harden
`modify_source_code`.** Both need the same per-language verification gate; build
it here, in the greenfield tool, then let hardening reuse a proven gate instead
of debugging a new gate and a delicate 1,200-line engine refactor at once.
Rationale:

1. **Low-risk vehicle for the shared gate** — apply a known-good gate to the
   hard engine later, rather than building both at once.
2. **De-risks `modify_source_code` before touching it** — once routing steers
   mechanical edits here, the risky LLM-regen path simply runs less often.
3. **Early shippable value** — Phases 1–4 are useful with no gate at all (the
   gate is P5); hardening has no comparable early-win structure.
4. **Value-per-risk** — this is high-value/low-risk; hardening is
   high-value/higher-risk. Lead with the compounding low-risk win.

```
Bulk tool P1–P4 (capability, no gate)
   └─► Bulk tool P5: build the shared verification gate HERE
          └─► Harden modify_source_code: reuse the proven gate
                + collateral guard + syntax-aware boundaries
```

**Flip condition:** if `modify_source_code` is invoked *frequently* in real
usage, or has already caused a bad collateral rewrite, the live risk outranks
this elegance — **harden first.** Settle it with the Phase-6 instrumentation in
`PLAN_HARDEN_EDIT.md` (how often the LLM picks `modify_source_code` over the
surgical tools): high usage → harden first; low usage (expected, since it is a
steered-away-from fallback) → this tool first.

---

## Phase 0 — Foundations (reuse audit)
**Goal:** Confirm the machinery to reuse before writing new code.
- [done] `text_file_str_replace_in_file`, `_compute_and_print_diff`,
  `check_write_size`, atomic-write idiom all exist in `lib/text_file_editor.py`.
- Decide verification-gate sequencing vs. `PLAN_HARDEN_EDIT.md`.
**Exit criteria:** Reuse list confirmed; gate ownership decided.
**Risk:** Low.

## Phase 1 — Literal single-file replace-all
**Goal:** The deterministic core, narrowest useful slice.
- `bulk_replace_in_files` for ONE file, literal match, replace-all, exact count.
- Structured return envelope; `check_write_size` cap; atomic write.
- Register in `AVAILABLE_TOOLS` + TOOLS schema.
**Exit criteria:** Renames every literal occurrence in a single file and reports
an accurate count; registered and callable.
**Risk:** Low. Pure deterministic string work.

## Phase 2 — Dry-run / preview
**Goal:** Make the safe mode the default before enabling multi-file.
- `dry_run=True` default; per-file unified diff via `_compute_and_print_diff`;
  no write unless `dry_run=False`.
**Exit criteria:** Preview returns accurate diffs and writes nothing; explicit
opt-in required to commit.
**Risk:** Low.

## Phase 3 — Safe matching options
**Goal:** Eliminate the silent-corruption classes.
- `word_boundary` (whole-identifier match — the rename killer feature).
- `literal=False` regex opt-in, pinned to Python `re`; compile errors → clean
  failure, no write.
- `expected_count` latch.
**Exit criteria:** `count` vs `account` test passes; bad regex fails cleanly;
count-mismatch aborts.
**Risk:** Low-Medium. Word-boundary + regex edge cases need tests.

## Phase 4 — Multi-file scope
**Goal:** Replace across a resolved file set.
- `paths` accepts explicit files and/or glob; resolve + report the list.
- Skip binaries / out-of-tree; per-file counts.
**Exit criteria:** Glob-scoped replace reports per-file counts and the resolved
list; no implicit whole-tree.
**Risk:** Medium. Glob resolution + scope safety.

## Phase 5 — Verification gate + batch atomicity
**Goal:** No broken or half-applied writes, ever.
- Per-language validator before write (shared with `PLAN_HARDEN_EDIT.md`).
- Batch all-or-nothing: compute + verify all, then commit; else clean summary.
**Exit criteria:** A syntax-breaking substitution is rejected unwritten; a bad
file in a batch aborts the batch with nothing half-written.
**Risk:** Medium. Depends on the shared verification gate.

## Phase 6 — Routing & docs
**Goal:** The model reaches for the right tool.
- Tool description routes mechanical → this / single → str-replace / fuzzy →
  `modify_source_code`.
- Document as the sanctioned mechanical-edit path.
**Exit criteria:** Description steers usage; `sed` and parallel bulk tools are
explicitly unnecessary.
**Risk:** Low.

---

## Dependency graph
```
P0 ─► P1 ─► P2 ─► P3 ─► P4 ─► P5 ─► P6
                              ▲
                              └── shared verification gate
                                  (PLAN_HARDEN_EDIT Part 1)
```

## Highest-risk items (watch these)
1. **Phase 5 batch atomicity** — partial application across files is the worst
   failure; all-or-nothing (or an explicit summary) is mandatory.
2. **Phase 3 word-boundary correctness** — getting identifier boundaries right
   is what makes renames trustworthy; substring bugs corrupt silently.
3. **Phase 4 scope safety** — never resolve to the whole tree by accident.

## Out of scope (explicitly deferred)
- Raw `sed` / regex-shell tools (rejected — footguns; see PLAN).
- Generic shell-exec for the LLM (Monitor exposes none today; keep it that way).
- Fuzzy / semantic refactors (that is `modify_source_code`'s job).
- Interactive per-match confirmation UI (dry-run preview covers the need).
