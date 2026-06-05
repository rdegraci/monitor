# Plan: Harden the Edit Engine

> Scope: `src/monitor/` only — chiefly `lib/protocol_engine.py` and the
> `modify_source_code` tool. This is a design spec, not implemented code.
> Goal: close the one place where mature edit tools (Aider et al.) have a real,
> hard-won lead — the **verify-and-reflect loop** around edits, and the
> **safety of the whole-file regeneration fallback**.

## Sequencing decision: do this AFTER the deterministic bulk-replace tool

**Default order: build the deterministic bulk-replace tool first
(`PLAN_DETERMINISTIC_BULK_REPLACE_TOOL.md`), then harden `modify_source_code`.**
Both need the same per-language verification gate (Part 1 here); building it
first in the greenfield bulk tool means this hardening reuses a *proven* gate
rather than introducing a new gate and a delicate 1,200-line engine refactor at
the same time. The bulk tool also de-risks `modify_source_code` before it is
touched — once routing steers mechanical edits to the deterministic tool, this
risky LLM-regen path simply runs less often.

```
Bulk tool P1–P4 (capability, no gate)
   └─► Bulk tool P5: build the shared verification gate THERE
          └─► (this plan) Harden modify_source_code: reuse the proven gate
                + collateral guard (Part 2) + syntax-aware boundaries (Part 3)
```

**Flip condition:** if `modify_source_code` is invoked *frequently* in real
usage, or has already caused a bad collateral rewrite, the live risk outranks
the elegance — **do this hardening first.** Settle it with the Part 6
instrumentation below (how often the LLM picks `modify_source_code` over the
surgical tools): high usage → harden first; low usage (expected, since it is a
steered-away-from fallback) → bulk tool first.

## Background: Monitor has a two-tier edit system

**Tier 1 — surgical, deterministic edits (the *preferred* path).**
`text_file_str_replace_in_file`, `text_file_insert_text_at_line`,
`text_file_create` (`tool_definitions.py:38-40`). Exact text edits, applied
directly, **no second LLM**. The `modify_source_code` tool description already
steers the model here first (`tool_definitions.py:289-300`, `:450`, `:840`).
This is the same philosophy the field has converged on — Monitor is **not**
behind on edit philosophy.

**Tier 2 — `modify_source_code` / `ProtocolEngine` (explicit *fallback*).**
For fuzzy intent ("make this idiomatic") or sweeping multi-site refactors. It
takes the **whole file + a natural-language request** and **regenerates the
file in chunks**:
- `_make_chunk_plan` (`:122`) splits on **fixed line counts**
  (`MAX_LINES_PER_CHUNK = 1000`, up to 15000 — `:824`, `:844`).
- `fetch_modified_script` (`:145`) orchestrates with global modification-cycle
  retry; `_modification_cycle` supports checkpoint/resume.
- `_send_request_with_compliance_retry` (`:349`) + `_request_chunk_correction`
  (`:189`) handle **format** non-compliance per chunk.
- `_collect_chunks` (`:542`) → `_parse_chunks` (`:680`) → `_assemble_and_save`
  (`:695`) joins chunks, normalizes whitespace, and `_atomic_write_text`
  (`:49`) writes.

## Where the risk concentrates

All editing risk lives in **tier 2**, because whole-file regeneration is the
most failure-prone editing strategy there is. Three failure modes are inherent:

1. **Silent collateral change.** The model rewrites the *whole file*, so it can
   quietly alter, drop, or "helpfully improve" lines never targeted by the
   request (the lazy-omission / `# ... rest unchanged ...` problem). Diff-apply
   engines structurally cannot do this; regeneration is maximally exposed.
2. **Chunk-boundary mangling.** Fixed-line splitting (`_make_chunk_plan`) can
   put a boundary inside a multi-line string, heredoc, long function, or
   bracket-balanced block — inviting mis-reassembly or broken syntax at the
   seam. (Risk is concentrated in large files; small files are single-chunk.)
3. **No semantic gate on the result.** Confirmed: `_assemble_and_save` (`:695`)
   does **no** parse check and **no** collateral diff — it joins, normalizes
   whitespace, and writes. Compliance retry validates *output format*, not
   whether the assembled file *parses* or *only changed what was intended*.
   Verification is left to the agent loop (`run_python_tests`,
   `type_check_python`), not enforced by the edit itself.

The gap with Aider was never "they have diffs." Monitor has deterministic
surgical edits already. The gap is the **apply → verify → reflect-on-failure
loop**, and the **safety of the regen fallback**. Everything below closes those.

---

## Part 1 — Post-assembly verification gate (the keystone)

The single biggest robustness win. Before the atomic write commits, validate the
assembled file; on failure, reject and retry instead of writing broken code.

- **Hook point:** inside `_assemble_and_save` (`:695`), after `full_script` is
  built and *before* `_atomic_write_text`.
- **Tiered validators** (pluggable, keyed by file extension) — the SAME three
  tiers as `PLAN_DETERMINISTIC_BULK_REPLACE_TOOL.md` Part 5 (shared, no fork):
  - Tier 1 — code: Python (`.py`) `ast.parse` — cheap, no execution;
    Swift (`.swift`) `swiftc -parse` (or `swift build` when in a package).
  - Tier 2 — structured text: `.json` `json.loads`, `.yaml`/`.yml`
    `yaml.safe_load`, `.toml` `tomllib.load`, `.xml` XML parse.
  - Tier 3 — freeform text (`.md`, `.txt`, …) and truly unknown extensions:
    skip with a logged note (never block).
- **Swift single-file caveat.** `swiftc -parse` runs only the parser (no build,
  no output) — the right mode for a syntax gate. But run on a *single* file it
  can report errors for things that are fine in the full module (missing
  imports, symbols defined elsewhere). Pure *parse* errors are about malformed
  syntax, not missing symbols, so a syntax-only gate is usually safe — but this
  must be tested, and it is a concrete reason verification **degrades to a
  logged skip rather than a hard block** when a validator proves unreliable for
  a language. Same applies if `swiftc` isn't on PATH (no toolchain) → skip.
- **On failure:** do NOT write. Return a structured failure carrying the
  validator error (file, line, message) so the reflection loop (Part 4) can act.
- **Invariant:** a tier-2 edit either writes a file that passes its validator,
  or writes nothing and reports why. No silent broken writes.

This converts "silently wrote broken code" → "couldn't produce valid code, here
is the error." It is the *verify* link Monitor is missing; retry already exists.

---

## Part 2 — Collateral-change guard

Whole-file regen's #1 real-world failure is touching code it shouldn't. Guard it.

- **Hook point:** `_assemble_and_save` (`:695`), after verification (Part 1),
  before write. Requires the *original* source (already available to the engine
  as `script_content` in `fetch_modified_script`).
- **Mechanism:** diff `full_script` against the original. Compute a change
  footprint (hunks, lines added/removed).
- **Policy (start conservative, tune):**
  - If the footprint is large relative to the `modification_request`'s apparent
    scope, treat it as suspicious → require confirmation or reflection rather
    than writing blind.
  - At minimum, **log the diff summary** on every tier-2 edit so collateral
    changes are visible after the fact (no silent truncation of what changed).
- **Note:** this is a heuristic, not a proof. Its job is to catch the egregious
  "rewrote half the file" case before it reaches disk, not to be exact.

---

## Part 3 — Syntax-aware chunk boundaries

Kill the boundary-mangling class of bugs (failure mode 2) at the source.

- **Hook point:** `_make_chunk_plan` (`:122`).
- **Change:** instead of cutting at fixed `lines_per_chunk`, snap each boundary
  to the nearest *safe* point at or before the target line:
  - a blank line at bracket/paren/brace depth zero, or
  - a top-level `def` / `class` / declaration boundary.
- **Keep** `MAX_LINES_PER_CHUNK` as the upper bound; only move the cut *earlier*
  to a safe seam. Never split inside a string literal or unbalanced block.
- **Scope note:** mostly matters for large multi-chunk files; single-chunk edits
  (the common case) are unaffected. Localized, contained change.

---

## Part 4 — Reflection loop on verification failure

Extend the existing correction machinery from *format* compliance to *semantic*
correctness — this is what makes mature editors feel reliable.

- **Reuse:** the pattern in `_request_chunk_correction` (`:189`) /
  `_send_request_with_compliance_retry` (`:349`).
- **New trigger:** a Part 1 validator failure (or a Part 2 suspicious footprint)
  produces a *targeted* correction prompt: "the assembled file fails to parse at
  line N: <error>; fix only that, change nothing else."
- **Bound it:** cap reflection attempts (reuse the existing retry budget in
  `fetch_modified_script` `:145`); on exhaustion, fail cleanly with the last
  error rather than writing.

Apply → verify → reflect → (write | clean failure). That closed loop is the
Aider-equivalent strength.

---

## Part 5 — Adversarial test corpus

The "pressure-test against gnarly edits" — and a permanent regression guard.

- A fixed fixture set exercising the hard cases:
  - heredocs / triple-quoted multi-line strings,
  - edits deliberately near a chunk boundary,
  - files spanning many chunks (> `MAX_LINES_PER_CHUNK`),
  - unicode / mixed line endings,
  - deeply nested brackets,
  - "change one function in a 2000-line file" (collateral-change bait).
- **Assertions per case:**
  1. the intended change is applied,
  2. **every untouched region is byte-identical** to the original,
  3. the result passes its language validator (Part 1).
- This harness is what tells you tier 2 is trustworthy, and it locks the
  guarantee in forever.

---

## Part 6 — Strengthen the bias toward tier 1

The safest regeneration is the one that never runs.

- **Instrument** how often `modify_source_code` is chosen over the surgical
  tools. If tier-2 usage is high, the steering prompt
  (`tool_definitions.py:289-300`) needs strengthening — most edits should be
  exact, reviewable, single-LLM surgical edits.
- This is measurement + prompt tuning, not engine work, but it caps how much any
  tier-2 risk can ever bite.

---

## What this pins down

- **Verification gate** (Part 1): tier-2 never silently writes broken code.
- **Collateral guard** (Part 2): unintended rewrites are caught or at least
  surfaced before disk.
- **Safe boundaries** (Part 3): no more mid-construct chunk seams.
- **Reflection** (Part 4): syntax/semantic failures drive targeted retries, not
  blind writes — the apply/verify/reflect loop that defines reliable editors.
- **Corpus** (Part 5): trustworthiness is measured and regression-locked.
- **Tier-1 bias** (Part 6): the risky path runs as rarely as possible.

None of this is a rewrite — it is a verification gate, a guard, smarter
boundaries, a reflection loop, and a test corpus, all localized to
`protocol_engine.py` and the assembly path.

## Preserved decisions (do not regress)

- **Two-tier design stays.** Surgical (tier 1) is preferred; regeneration
  (tier 2) is the fallback. Do not collapse them.
- **Atomic write** (`_atomic_write_text` `:49`) and **checkpoint/resume**
  (`_modification_cycle`) stay — verification slots *in front of* the write, it
  does not replace these.
- **Never block on an unknown language** — verification degrades to a logged
  skip, not a hard failure.
- **Backend stays synchronous** (consistent with the rest of `src/monitor/`).
