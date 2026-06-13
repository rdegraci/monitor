# Monitor Wiki Linter Plan

## Objective
Add a separate monitor-wiki linter capability that checks project wiki content
for structural issues, likely staleness, and contradictions with the codebase
without overloading the main Monitor code-writing workflow.

## Scope
The monitor-wiki linter should eventually support:
- structural validation of project wiki files
- optional LLM-assisted semantic drift detection
- explicit or on-demand execution instead of constant background use
- discrepancy reporting with actionable recommendations
- separation from the main coding assistant flow

## Design goals
- Keep the linter independent from the first monitor-wiki provisioning feature.
- Prefer explicit or discrepancy-triggered runs over always-on validation.
- Separate cheap deterministic checks from expensive LLM-assisted checks.
- Prefer code and newer project-local docs over stale wiki content.
- Produce focused findings rather than broad speculative rewrites.

## Functional areas
### Structural linting
- verify `INDEX.md` exists when a project wiki is expected
- verify referenced wiki pages exist
- verify referenced code paths still exist where applicable
- detect obviously oversized or orphaned wiki pages
- detect wiki pages that are no longer reachable from the index


### Semantic linting v1 design direction
Semantic linting v1 should be intentionally narrow and low-noise.

Initial in-scope claim types:
- stable architecture claims
- workflow claims that affect how developers build, test, or validate changes
- ownership or routing claims that affect where a developer should make a
  change

Initial out-of-scope areas:
- stylistic rewrite advice
- broad page-quality judgments
- speculative contradictions without explicit code or newer-doc evidence
- aspirational or non-committal prose that is not clearly a current claim

A semantic contradiction should be treated as material only when it would
likely mislead a coding task about subsystem ownership, code location,
authoritative docs, or validation workflow.

Semantic findings should be reported only when they can cite both the wiki
claim and the contradicting evidence from code or newer project-local docs.
When evidence is ambiguous, semantic linting should prefer no finding.
### Semantic linting
- compare stable wiki claims against the current codebase
- detect likely stale ownership, workflow, or architecture statements
- identify wiki/code contradictions that would materially affect coding tasks
- suggest focused updates rather than broad rewrites

### Implemented semantic expansion
The current semantic expansion prioritizes additional finding kinds that are
path-grounded, low-noise, and compatible with narrow localized fixes.

Implemented finding kinds:
- `semantic_stale_authority_claim`
- `semantic_stale_workflow_claim`
- `semantic_stale_ownership_claim`

Implemented shape:
- detect claim-bearing wiki lines for each category
- require an explicit repo-relative path in the line
- emit a distinct semantic finding kind only when that path no longer exists
- reuse the same `:wiki_fix` preview/apply machinery when the fix is a
  localized sentence rewrite
- defer broader architecture contradiction inference and broad completeness
  judgments until later phases

## Architecture direction
The monitor-wiki linter should be a separate component from the main coding
flow, likely with its own module or class.

A likely shape is:
- structural linting helpers for deterministic checks
- a dedicated linter service or class for orchestration
- a distinct LLM prompt for semantic drift detection
- optional separate model and reasoning configuration for linter tasks

## Operational model
- do not run the linter automatically on every startup
- do not run the linter automatically on every code change
- run the linter when explicitly requested or when a material wiki/code
  discrepancy is detected
- keep the linter usable as a maintenance tool rather than mandatory overhead
- keep high-level linter behavior documented in `src/monitor/MONITOR.md` and
  reinforced concisely in `src/monitor/lib/system_prompt.py`, while leaving
  detailed lint heuristics and workflow design in dedicated wiki-linter docs

## Open decisions
- whether discrepancy-triggered linting should be added in addition to the
  built-in command
- whether semantic linting should use a dedicated model configuration
- how strongly the linter should recommend wiki updates versus directly writing
  them

## Risks
- false positives from heuristic semantic checking
- spending too many tokens on broad semantic review
- turning the linter into an always-on burden instead of a focused tool
- overcorrecting wiki style instead of finding meaningful discrepancies

## Success criteria
- structural wiki issues can be detected reliably
- semantic drift can be surfaced when needed without excessive noise
- linter findings are focused and actionable
- the linter remains separate from the main code-writing behavior

## Current implementation status
- a dedicated structural linter module now exists at
  `src/monitor/lib/monitor_wiki_linter.py`
- the current implementation is deterministic-only and covers missing index,
  broken references, missing repo-relative path references, oversized markdown
  pages, low-signal markdown pages, and orphaned markdown pages
- structural findings now use stable fields including `kind`, `severity`,
  `page`, `path`, `message`, and `suggestion`
- a human-readable report formatter now exists for PASS/FAIL summaries,
  per-severity grouping, and actionable suggestions
- a simple invocation helper now exists to return both structured lint output
  and a formatted report in one call
- a built-in `:wiki_lint` command now exists to run the configured project
  wiki linter and print its report
- `:wiki_lint` now supports explicit `structural`, `semantic`, and `all`
  modes while defaulting to structural mode when no argument is provided
- wiki-lint execution now flows through mode-aware orchestrators in
  `src/monitor/lib/monitor_wiki_linter.py`
- semantic mode now implements a narrow semantic v1 check for stale
  location/path claims in wiki lines that assert implementation locations such
- `:wiki_fix` now also supports explicit `auto_all` to preview then apply all
  supported semantic findings in one batch command while still ignoring
  unsupported finding kinds
  as `lives in`, `implemented in`, `defined in`, or `authoritative
  implementation`
- semantic mode now also implements stale authority/document claim detection
  for claim-bearing lines using phrases such as `authoritative doc`,
  `source of truth`, `canonical guide`, or `official guide`
- semantic mode now also implements stale workflow claim detection for
  claim-bearing lines using phrases such as `instructions live in`,
  `documented in`, `build steps are in`, or `test workflow is in`
- semantic mode now also implements stale ownership/routing claim detection
  for claim-bearing lines using phrases such as `owned by`,
  `ownership lives in`, `routing lives in`, `changes belong in`, or
  `handled in`
- semantic findings are currently emitted only when those claim-bearing lines
  cite repo-relative paths that no longer exist
- latest wiki-lint results are now stored in-process with stable finding ids so
  later workflows such as `:wiki_fix llm <finding_id>` can resolve one finding
  at a time
- `:wiki_fix` now supports previewing a narrow LLM-drafted wiki update for a
  supported semantic stale-location, stale-authority, stale-workflow, or
  stale-ownership finding and then applying that reviewed draft to disk with
  `:wiki_fix apply <finding_id>`
- `:wiki_fix` now also supports explicit `llm_all` and `apply_all` workflows
  for all supported semantic findings from the latest stored lint result
- apply mode now reuses the exact stored preview rather than regenerating text
  at apply time, both for one-finding and all-findings workflows
- ownership/routing validation coverage now includes existing-path PASS,
  non-claim ignore behavior, alternate phrase detection, ownership
  `:wiki_fix apply` coverage, and batch `wiki_fix` workflow coverage in
  targeted tests
