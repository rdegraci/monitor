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
- unchecked semantic and workflow items below remain future work

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

## Architecture
- [ ] Decide whether to implement the linter as its own class or service.
- [ ] Decide where deterministic lint helpers should live.
- [ ] Decide whether the linter should have its own prompt template.
- [ ] Decide whether the linter should have its own model and reasoning configuration.
- [ ] Keep the linter separated from the normal code-writing path.

## Workflow and UX
- [x] Decide whether the linter is exposed through a built-in command.
- [x] Decide whether structural linting can be run without semantic linting.
- [x] Decide what output shape is preferred for findings and recommendations.
- [ ] Decide whether wiki updates are only suggested or may be applied in a dedicated workflow.

- [x] Decide whether structural and semantic linting should be separately invocable.
## Testing
- [x] Add tests for structural lint checks.
- [x] Add tests for broken-link detection.
- [x] Add tests for orphaned-page detection.
- [x] Add tests for missing-file reference detection.
- [x] Add tests for semantic conflict reporting behavior.
- [ ] Add tests for keeping the linter isolated from normal startup behavior.

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
