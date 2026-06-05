# Checklist: Deterministic Bulk-Replace Tool

Build-order task list derived from `PLAN_DETERMINISTIC_BULK_REPLACE_TOOL.md`.
Check items as completed. `[x]` marks reusable machinery that already exists.

> Fills the empty middle cell: single-site (exists) → **deterministic bulk**
> (this) → fuzzy LLM refactor (`modify_source_code`). No `sed`.

> **IMPLEMENTED (2026-06-04).** Phases 1–6 are built and tested:
> - Tool: `src/monitor/lib/bulk_replace.py` (`bulk_replace_in_files`).
> - Shared verification gate: `src/monitor/lib/edit_verification.py`
>   (three tiers; reusable by the `modify_source_code` hardening work).
> - Registered in `src/monitor/lib/tool_definitions.py` (`AVAILABLE_TOOLS`,
>   `TOOL_DESCRIPTIONS`, `GEMINI_TOOL_DESCRIPTIONS`).
> - Tests: `tests/monitor/lib/test_bulk_replace.py` — 21 tests; full suite
>   880 passed / 1 skipped, no regressions.
> Note: `check_write_size` is imported lazily inside the function to avoid the
> pre-existing `config → core.tools → tool_definitions` import cycle (same
> approach the surgical editors use). The verification gate now exists, so the
> edit-hardening plan can reuse it rather than building its own.

## 0. Pre-flight
- [x] Single-site editor exists: `text_file_str_replace_in_file`
      (`text_file_editor.py:274`, exactly-one-match).
- [x] Diff renderer exists: `_compute_and_print_diff` (reuse for previews).
- [x] Write-size cap exists: `check_write_size` (`text_file_editor.py:287`).
- [x] No generic shell-exec tool exposed to the LLM — keep that posture.
- [ ] Confirm the verification gate from `PLAN_HARDEN_EDIT.md` Part 1 is
      available (or sequence this tool after it so the gate can be shared).

## 1. Tool surface
- [ ] Implement `bulk_replace_in_files(old, new, paths, literal=True,
      word_boundary=False, expected_count=None, dry_run=True)`.
- [ ] Register in `AVAILABLE_TOOLS` dispatch map (`lib/tool_definitions.py`).
- [ ] Add the canonical TOOLS JSON schema entry (`lib/tool_definitions.py`).
- [ ] Structured return envelope:
      `{ok, occurrences, files_changed, per_file:[{path,count,diff}], message}`.

## 2. Matching semantics
- [ ] Literal substring replacement when `literal=True` (default) — no regex.
- [ ] Regex opt-in when `literal=False`; compile errors → clean failure, no write.
- [ ] Pin regex dialect to Python `re` (one well-defined dialect, not sed).
- [ ] `word_boundary=True` matches whole identifiers only (rename `count` does
      NOT touch `account`).
- [ ] Replace ALL occurrences, but always report the exact count.

## 3. Scope & multi-file
- [ ] `paths` accepts explicit file(s) and/or a glob; resolve to a concrete list.
- [ ] NEVER default to whole-tree; require explicit paths/glob.
- [ ] Report the resolved file list with the result.
- [ ] Skip binary files and anything outside the repo working tree.

## 4. Dry-run / preview (default ON)
- [ ] `dry_run=True` default: compute + return per-file unified diff, NO write.
- [ ] Reuse `_compute_and_print_diff` so previews match surgical-tool format.
- [ ] Writing requires explicit `dry_run=False` (dangerous op is the explicit one).

## 5. Verification gate — three tiers (shared with PLAN_HARDEN_EDIT)
- [ ] Tier 1 — code: parse/compile check (Python `ast.parse`;
      Swift `swiftc -parse`).
- [ ] Tier 2 — structured text: structural parse for `.json` (`json.loads`),
      `.yaml`/`.yml` (`yaml.safe_load`), `.toml` (`tomllib.load`), `.xml` (XML parse).
- [ ] Tier 3 — freeform text (`.md`, `.txt`, logs): skip (nothing to validate).
- [ ] Truly unknown extension → logged skip, never hard-block.
- [ ] File failing verification is NOT written; error returned.
- [ ] Validator keyed by file type/extension; tiers are data-driven (easy to
      add formats).
- [ ] Share the validator implementation with `PLAN_HARDEN_EDIT.md` (no fork).

## 6. Write safety & atomicity
- [ ] Apply `check_write_size` blast-radius cap to `new`.
- [ ] Atomic per-file write (reuse existing atomic-write idiom).
- [ ] `expected_count` latch: if provided and actual != expected → fail, no write.
- [ ] Batch all-or-nothing: compute + verify all, then commit; mid-batch failure
      leaves NO half-applied rename.
- [ ] If all-or-nothing is impractical for large sets, per-file commit with an
      explicit applied/skipped summary — never silent partial success.

## 7. Prompt / routing guidance
- [ ] Tool description routes usage: mechanical multi-site → this tool; single
      unique edit → `text_file_str_replace_in_file`; fuzzy → `modify_source_code`.
- [ ] Document this as the sanctioned mechanical-edit path (so `modify_source_code`
      is reserved for fuzzy changes and `sed` is never proposed).

## 8. Tests
- [ ] Literal replace-all across multiple sites in one file (count correct).
- [ ] Multi-file via glob (per-file counts + resolved list reported).
- [ ] `word_boundary` does NOT match substrings (`count` vs `account`).
- [ ] Regex opt-in path; invalid regex → clean failure, no write.
- [ ] `expected_count` mismatch → fail, no write.
- [ ] `dry_run=True` writes nothing but returns accurate diffs.
- [ ] Verification gate rejects a substitution that breaks code syntax.
- [ ] Verification gate rejects a substitution that breaks structured text
      (e.g. turns valid `.json` invalid); freeform `.txt`/`.md` writes fine.
- [ ] Batch atomicity: one bad file aborts the batch with nothing half-written.
- [ ] Binary / out-of-tree files skipped.
