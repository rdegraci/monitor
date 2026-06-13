# Monitor Wiki Linter Checklist

## Discovery and Design
- [x] Define the purpose of the wiki-linter separately from monitor-wiki provisioning.
- [x] Define the boundary between structural linting and semantic linting.
- [x] Decide when the linter should run.
- [x] Decide how linter findings should be surfaced.
- [x] Decide whether the linter is user-invoked, discrepancy-invoked, or both.

Current implementation status:
- structural linting now has an initial deterministic implementation in
  `src/monitor/lib/monitor_wiki_linter.py`
- implemented deterministic checks now cover missing index, broken wiki-page
  references, missing repo-relative path references, oversized markdown pages,
  low-signal markdown pages, and orphaned markdown pages
- semantic linting now has a narrow v1 implementation for stale
  location/path claims, stale authority/document claims, stale workflow
  claims, and stale ownership/routing claims in claim-bearing wiki lines
- `:wiki_lint` now supports explicit `structural`, `semantic`, and `all`
  modes, and latest results are stored in-process for explicit follow-up
  workflows such as `wiki_fix`
- `:wiki_fix` now supports `llm` preview mode and `apply` mode for supported
  semantic stale-location, stale-authority, stale-workflow, and
  stale-ownership findings, with apply reusing the reviewed preview
- `:wiki_fix` now also supports explicit `llm_all` and `apply_all` workflows
  for supported semantic findings from the latest stored lint result
- ownership/routing validation coverage now includes existing-path PASS,
  non-claim ignore behavior, and alternate phrase detection in semantic lint
  tests, plus `:wiki_fix apply` coverage for ownership findings
- unchecked broader semantic and workflow items below remain future work

## Structural Linting
- [x] Check for missing `INDEX.md` when a project wiki should exist.
- [x] Check for broken links between wiki pages.
- [x] Check for referenced code paths that no longer exist.
- [x] Check for orphaned wiki pages not reachable from `INDEX.md`.
- [x] Check for oversized wiki pages.
- [x] Check for low-signal wiki pages.

## Semantic Linting
- [x] Define what kinds of wiki claims should be compared against code.
- [x] Define how to detect stale architecture, workflow, and ownership statements.
- [x] Define when a wiki/code contradiction is considered material.
- [x] Ensure semantic linting prefers code over stale wiki content.
- [x] Ensure semantic linting recommends focused updates rather than broad rewrites.
- [x] Add `semantic_stale_authority_claim` detection for claim-bearing lines
  with missing repo-relative paths.
- [x] Add `semantic_stale_workflow_claim` detection for claim-bearing lines
  with missing repo-relative paths.
- [x] Add `semantic_stale_ownership_claim` detection for claim-bearing lines
  with missing repo-relative paths.
- [x] Reuse narrow `:wiki_fix` preview/apply support for newly supported
  semantic finding kinds that can be fixed with one localized sentence rewrite.

## Architecture
- [ ] Decide whether to implement the linter as its own class or service.
- [x] Decide where deterministic lint helpers should live.
- [ ] Decide whether the linter should have its own prompt template.
- [ ] Decide whether the linter should have its own model and reasoning configuration.
- [x] Keep the linter separated from the normal code-writing path.

## Workflow and UX
- [x] Decide whether the linter is exposed through a built-in command.
- [x] Decide whether structural linting can be run without semantic linting.
- [x] Decide what output shape is preferred for findings and recommendations.
- [x] Decide whether wiki updates are only suggested or may be applied in a dedicated workflow.
- [x] Add explicit batch auto-fix for supported semantic finding kinds only.
- [x] Add a preview/apply-all workflow for supported semantic finding kinds.

- [x] Decide whether structural and semantic linting should be separately invocable.
## Testing
- [x] Add tests for structural lint checks.
- [x] Add tests for broken-link detection.
- [x] Add tests for orphaned-page detection.
- [x] Add tests for missing-file reference detection.
- [x] Add tests for semantic conflict reporting behavior.
- [x] Add tests for ownership/routing semantic detection coverage, including
  existing-path PASS behavior, non-claim ignore behavior, and alternate
  ownership phrase detection.
- [x] Add tests for ownership `:wiki_fix apply` behavior.
- [x] Add tests for `:wiki_fix llm_all` and `:wiki_fix apply_all` behavior.
- [x] Add tests for keeping the linter isolated from normal startup behavior.

## Documentation
- [x] Document the purpose of the wiki-linter.
- [x] Document when it should be run.
- [x] Document the difference between structural and semantic linting.
- [x] Document how findings should be interpreted.
- [x] Document whether and how it can suggest wiki updates.
- [x] Decide that lint findings should feed a separate explicit wiki-fix workflow rather than automatic rewriting.

## Validation
- [ ] Verify structural linting is cheap and deterministic.
- [ ] Verify semantic linting is not excessively noisy.
- [ ] Verify code wins when code and wiki disagree.
- [ ] Verify the linter improves wiki reliability without becoming mandatory overhead.
