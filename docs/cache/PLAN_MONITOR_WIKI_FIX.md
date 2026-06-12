# Monitor Wiki Fix Plan

## Objective
Design a separate, explicit workflow that consumes monitor-wiki lint findings
and drafts minimal wiki updates without turning linting into automatic wiki
rewriting.

## Why this exists
The monitor-wiki linter now produces structured findings for both structural and
narrow semantic issues. Those findings are useful as inputs to a constrained
repair workflow, but they should not directly trigger automatic wiki edits.

The wiki-fix workflow should bridge that gap by:
- consuming structured lint findings
- drafting minimal, targeted wiki updates
- showing reviewable output before any write
- remaining separate from the normal code-writing workflow

## Design goals
- Keep wiki fixing separate from wiki linting.
- Require explicit invocation.
- Prefer minimal edits over broad page rewrites.
- Preserve human review before writes.
- Use structured findings to constrain scope and reduce hallucination.
- Prefer deterministic edits when a safe exact replacement is possible.
- Use LLM assistance only when the fix requires sentence-level rewriting.

## Non-goals
- automatic wiki rewriting after lint runs
- broad stylistic rewriting of wiki pages
- whole-page regeneration when a one-line or one-section fix is enough
- using wiki fixing as a substitute for code inspection

## Proposed command shape
The current initial command surface is:
- `:wiki_lint [mode]`
- `:wiki_fix llm <finding_id>`

Current `:wiki_fix` behavior:
- explicit LLM-assisted preview mode only
- one finding at a time
- consumes the latest stored wiki-lint result from the current process
- supports only `semantic_stale_location_claim` findings
- prints a unified diff and does not write files
- validates the LLM replacement and refuses preview when the replacement is
  empty, unchanged, too large, too many lines, or would produce an overly
  large diff footprint

Possible later extensions:
- `:wiki_fix latest llm <finding_id>`
- `:wiki_fix all`
- `:wiki_fix apply llm <finding_id>`

For v1, the safest shape is one finding at a time.

## Workflow model
### Step 1: Produce findings
The user runs a lint pass explicitly.

Example:
- `:wiki_lint structural`
- `:wiki_lint semantic`
- `:wiki_lint all`

The lint pass produces structured findings with stable fields such as:
- `kind`
- `severity`
- `page`
- `path`
- `message`
- `suggestion`
- optional semantic fields such as `claim`, `evidence`, and `impact`

### Step 2: Select one finding
The user selects a single finding to fix.

The workflow should use a stable finding identifier derived from the latest lint
result rather than asking the user to restate the problem in free text.

### Step 3: Draft a constrained update
The wiki-fix workflow drafts a minimal update limited to:
- the affected wiki page
- the specific stale or broken claim
- the evidence already captured by the finding

The workflow should avoid touching unrelated lines or sections.

### Step 4: Show a diff
Before any write, the workflow should present a reviewable diff.

The diff should be small and localized. If the proposed change is broad, the
workflow should stop and ask for explicit confirmation or refuse the fix.

### Step 5: Apply only through explicit workflow
The workflow may apply the drafted change only because the user invoked the
explicit wiki-fix path.

Current implementation status:
- `:wiki_fix llm <finding_id>` is preview-only
- the current implementation prints a diff and returns preview metadata
- the current implementation does not write wiki files

Linting alone should never write wiki content.

## Finding storage model
The wiki-fix workflow needs a source of truth for the latest lint findings.

The current v1 approach is:
- store the latest lint result in memory for the active process/session
- include stable finding identifiers in that stored result
- let `:wiki_fix llm <finding_id>` resolve against the latest lint run

Alternative future options:
- write findings to a session-local file
- support reloading findings from a saved report
- support finding selection through an interactive picker

## Repair strategy by finding type
### Structural findings
Structural findings are often deterministic.

Examples:
- broken page reference
- missing repo-relative path reference
- orphaned page reference issue

Preferred strategy:
- use deterministic edits where the exact replacement is known
- avoid LLM rewriting when a safe literal fix is available

### Semantic findings
Semantic findings are often sentence-level edits.

Examples:
- stale location/path claim
- stale workflow sentence
- stale ownership sentence

Preferred strategy:
- constrain the LLM to rewrite only the affected claim or very small section
- provide the finding fields as hard constraints
- prohibit broad page cleanup or stylistic rewriting

## V1 scope recommendation
The initial wiki-fix implementation should support only one narrow semantic fix
family:
- semantic stale location/path claims

This is the best first target because:
- the affected line is usually easy to localize
- the evidence is explicit

## LLM-assisted wiki-fix mode
The current wiki-fix mode uses the LLM to draft a better localized replacement
for one selected finding.

This mode is optional and explicitly invoked.

The current command shape is:
- `:wiki_fix llm <finding_id>` for LLM-assisted preview

The LLM-assisted mode remains preview-only and does not write files.

### Required safety constraints
The LLM-assisted mode should receive only bounded inputs:
- the selected finding
- the affected wiki page text
- ideally a narrow excerpt around the affected claim rather than the full wiki
- the relevant evidence fields from the finding
- strict instructions to edit only the affected claim or smallest relevant
  section

The LLM-assisted mode should not receive unrelated wiki pages unless the fix
really requires them.

### Required output contract
The LLM should be asked to return only:
- the replacement text for the affected claim, or
- the smallest replacement block that contains the affected claim

It should not be asked to rewrite the whole page.
It should not be allowed to perform broad cleanup or style polishing.

### Preview-first behavior
The LLM-assisted mode should remain preview-first.

That means:
- generate a proposed localized update
- validate that the replacement stays within localized preview limits
- compute and show a diff
- do not write automatically
- require a later explicit apply path if writes are ever added

### Refusal behavior
The LLM-assisted mode should refuse or stop when:
- the targeted claim cannot be localized reliably in the page
- the replacement is empty or unchanged
- the replacement exceeds localized preview size limits
- the proposed replacement footprint expands beyond a small local block
- the resulting diff exceeds the configured local diff-footprint guard

Current preview guard defaults:
- maximum replacement lines: 3
- maximum replacement characters: 400
- maximum changed diff lines: 20
- the evidence is ambiguous
- the finding type is not supported by the constrained repair path

### Best first use
The first LLM-assisted use case should still be:
- semantic stale location/path claims

Even there, the model should only improve the sentence-level draft quality. It
should not broaden the scope of the fix.

- the replacement can often be narrowly drafted
- the risk of collateral rewrite is lower than for broader semantic claims

## Current recommendation
- keep `:wiki_fix llm <finding_id>` explicit and preview-only
- do not add implicit or automatic wiki-fix behavior
- keep all LLM-assisted fixes localized and constrained to one finding at a
  time until diff quality is proven acceptable

## Safety rules
- Do not rewrite the whole page unless the user explicitly requests that.
- Do not modify multiple pages in one fix operation for v1.
- Do not infer unrelated wiki changes from one finding.
- Refuse or fall back to preview-only when the proposed edit footprint is too large.
- Prefer preserving existing wording outside the stale claim.
- Prefer code and newer project-local documentation over stale wiki text.

## Output expectations
A wiki-fix operation should return:
- the selected finding id
- the affected page
- whether the proposal is preview-only or applied
- the proposed replacement summary
- a diff or diff-like preview
- any refusal reason if the workflow declines to apply

## Open decisions
- how finding ids are generated and surfaced to the user
- whether `:wiki_fix` should automatically rerun lint or consume only the latest
  stored lint result
- whether preview and apply should be separate submodes in v1
- whether deterministic and LLM-assisted fixes should share one entry point
- whether fix history should be recorded for later audit

## Recommended v1 summary
- keep wiki fixing separate from wiki linting
- require explicit invocation
- operate on one finding at a time
- support previewable, minimal diffs
- apply only within a dedicated fix workflow
- start with semantic stale location/path claim fixes
- avoid broad rewrites
