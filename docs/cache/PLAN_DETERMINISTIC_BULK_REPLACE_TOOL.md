# Plan: Deterministic Bulk-Replace Tool

> Scope: `src/monitor/` only — a new LLM-callable tool, alongside the existing
> editors in `lib/text_file_editor.py`. This is a design spec, not implemented
> code.
> Goal: fill the empty middle cell of Monitor's edit space — **deterministic,
> multi-site mechanical edits** — without an LLM in the loop and without the
> footguns of raw `sed`.

## Why this tool exists: the empty middle cell

Monitor's edit space is three cells, and the middle one is currently empty:

| Need | Tool today | Deterministic? |
|---|---|---|
| Single-site exact edit | `text_file_str_replace_in_file` (exactly-one-match) | ✅ yes |
| **Multi-site mechanical edit** | **— nothing —** | — |
| Sweeping / fuzzy refactor | `modify_source_code` (ProtocolEngine) | ❌ no — it's an LLM |

- `text_file_str_replace_in_file` **rejects** multi-match by design
  (`text_file_editor.py:310-318`) — it is strictly single-site.
- `ripgrep_search_tool` is read-only search, not replace.
- So "rename this exact symbol at all 40 call sites" today means either 40
  individual single-site calls, or handing a purely mechanical change to
  `modify_source_code` — which **regenerates the whole file via an LLM,
  non-deterministically**. That is overkill and re-introduces the
  collateral-drift risk that `PLAN_HARDEN_EDIT.md` exists to fight.

Using a probabilistic tool for a deterministic job is the wrong trade. This tool
is the deterministic path for mechanical multi-site edits.

## Why not `sed`

`sed` is the wrong *implementation* of the right idea (see the deeper rationale
in `PLAN_HARDEN_EDIT.md` discussion):
- LLMs write bad regex (unescaped metacharacters, greedy matches, over-match).
- `sed` applies to every match by default — maximal blast radius.
- BSD (macOS) vs GNU `sed` differ (`-i` argument, `-E`/`-r`, escape semantics);
  the model will emit GNU-isms that fail or misbehave on darwin.
- `sed -i` bypasses any verification or collateral guard.

This tool keeps the power and removes the footguns.

## Synergy with `PLAN_HARDEN_EDIT.md`

This is not parallel-bloat — it *reduces* risk. Every mechanical rename that
today must go through `modify_source_code` (the risky LLM-regen path) can
instead go through this deterministic, verified tool. Fewer tier-2 invocations →
less of the exact collateral risk the hardening plan targets. It also reuses the
hardening plan's verification gate (see Part 5). `modify_source_code` is then
reserved for genuinely *fuzzy* changes; nobody needs to reach for `sed`.

---

## Part 1 — Tool surface

Proposed name: `bulk_replace_in_files` (registered in `AVAILABLE_TOOLS` and the
canonical TOOLS schema in `lib/tool_definitions.py`, next to the other editors).

Parameters:
- `old` (str, required) — the text/pattern to find.
- `new` (str, required) — the replacement.
- `paths` (str | list, required) — explicit file path(s) and/or a glob
  (e.g. `src/**/*.py`). NEVER an implicit whole-tree default.
- `literal` (bool, default **true**) — literal match by default; regex strictly
  opt-in.
- `word_boundary` (bool, default false) — match only whole words/identifiers
  (e.g. rename `count` must not touch `account`).
- `expected_count` (int, optional) — if given, the tool asserts exactly this
  many replacements and fails otherwise (caller's safety latch).
- `dry_run` (bool, default **true**) — preview by default; must be explicitly
  set false to write.

Returns a structured envelope consistent with the existing editors:
`{ok, occurrences, files_changed, per_file: [{path, count, diff}], message}` on
success; `{ok: false, error}` on failure.

## Part 2 — Matching semantics (the safety core)

1. **Literal by default.** `literal=true` does exact substring replacement — no
   regex engine, no metacharacter interpretation. This is the common rename case
   and kills the bad-regex failure class outright.
2. **Regex opt-in only.** `literal=false` compiles `old` as a regex. Compile
   errors are returned as a clean failure, never a partial write. (Consider
   restricting to Python `re` semantics so behavior is one well-defined dialect,
   not shell-`sed` ambiguity.)
3. **Word-boundary option.** `word_boundary=true` wraps matches so only whole
   identifiers match — the killer feature for symbol renames, and exactly where
   naive substring / `sed` substitution silently corrupts code.
4. **All occurrences.** Unlike `text_file_str_replace_in_file`, this replaces
   every match — that is the entire point — but always **reports the exact
   count** so "replace all" is never silent.

## Part 3 — Scope & multi-file

- `paths` may be explicit files and/or a glob; resolve to a concrete file list
  up front and **report that list** before/with the result.
- Skip binary files and anything outside the repo working tree.
- Per-file results are independent: one file failing verification (Part 5) does
  not silently corrupt the batch — see Part 6 for batch atomicity.

## Part 4 — Dry-run / preview (default on)

- `dry_run=true` (default) computes and returns the unified diff per file
  **without writing** — reuse `_compute_and_print_diff` from
  `text_file_editor.py` so previews match the surgical tools' diff format.
- The model (or the user) reviews the preview, then re-issues with
  `dry_run=false` to commit. Preview-by-default makes the dangerous operation
  the explicit one.

## Part 5 — Verification gate (shared with PLAN_HARDEN_EDIT)

Before any write commits, run a validator on the resulting file content. "Non-
code text" is not monolithic — the gate has **three tiers**, keyed by file type:

| File kind | Examples | Validator |
|---|---|---|
| Code | `.py`, `.swift` | Parse/compile check (Python `ast.parse`; Swift `swiftc -parse`) |
| **Structured text** | `.json`, `.yaml`/`.yml`, `.toml`, `.xml` | **Structural parse** (`json.loads`, `yaml.safe_load`, `tomllib.load`, XML parse) |
| Freeform text | `.md`, `.txt`, logs, etc. | Skip — nothing to validate |

- The middle tier matters: a careless literal replace can silently turn a valid
  `config.json` into invalid JSON. Treating structured-data formats as
  validatable (not lumping them into "unknown → skip") catches that before it
  reaches disk.
- A file that fails verification is **not written**; its error is returned.
- Truly unknown extensions degrade to a logged skip (never hard-block).
- **Swift single-file caveat.** `swiftc -parse` runs only the parser (no build,
  no output) — the right mode for a syntax gate. But on a *single* file it can
  report errors for things that are fine in the full module (missing imports,
  symbols defined elsewhere). Pure *parse* errors are about malformed syntax,
  not missing symbols, so a syntax-only gate is usually safe — but this must be
  tested, and it is a concrete reason verification **degrades to a logged skip
  rather than a hard block** when a validator proves unreliable for a language.
  Same applies if `swiftc` isn't on PATH (no toolchain) → skip.
- This is why bulk replace is *safer* than routing mechanical edits through the
  LLM regen path: literal substitution can't hallucinate, and the gate catches
  the case where a substitution still breaks code or structured-data syntax.
- This tiered validator is the **shared** gate: `PLAN_HARDEN_EDIT.md` Part 1
  reuses the same three tiers (no fork).

## Part 6 — Write safety & atomicity

- Reuse `check_write_size` (already used by `text_file_str_replace_in_file`,
  `text_file_editor.py:287`) as a blast-radius cap.
- Atomic per-file write (reuse the atomic-write idiom).
- **Batch semantics:** default **all-or-nothing** across the resolved file set —
  compute all replacements + verify all, then commit, so a mid-batch failure
  never leaves a half-applied rename. (If all-or-nothing proves impractical for
  large sets, fall back to per-file commit with a clear summary of what was and
  wasn't applied — never silent partial success.)

## Part 7 — Prompt / routing guidance

- Tool description steers usage: **mechanical, exact multi-site edits → this
  tool**; single unique edit → `text_file_str_replace_in_file`; genuinely fuzzy
  ("make idiomatic") → `modify_source_code`.
- Record explicitly that this is the **sanctioned mechanical-edit path** so
  `modify_source_code` is reserved for fuzzy changes and `sed` is never needed.

---

## What this pins down

- **Determinism**: mechanical multi-site edits no longer require an LLM; same
  input → same output, reproducible, instant, zero token cost.
- **Safety over `sed`**: literal-by-default + word-boundary + regex-opt-in +
  dry-run-by-default + verification gate + count reporting.
- **Risk reduction**: offloads mechanical edits from `modify_source_code`,
  shrinking reliance on the risky LLM-regen path.
- **Completeness**: fills the middle cell so the edit space is single → bulk →
  sweeping, each with the right determinism profile.

## Preserved decisions (do not regress)

- **Three-tier edit space stays distinct.** Single-site, deterministic-bulk, and
  fuzzy-LLM are separate tools with separate jobs; do not collapse them.
- **No raw `sed` / no generic shell-exec** — the LLM's mutators stay scoped and
  structured (Monitor exposes no generic shell tool today; keep it that way).
- **Reuse, don't duplicate**: diff rendering (`_compute_and_print_diff`),
  size cap (`check_write_size`), atomic write, and the `PLAN_HARDEN_EDIT`
  verification gate are shared, not reimplemented.
- **Backend stays synchronous** (consistent with the rest of `src/monitor/`).
