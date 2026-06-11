# Monitor Wiki Linter Checklist

## Discovery and Design
- [x] Define the purpose of the wiki-linter separately from monitor-wiki provisioning.
- [x] Define the boundary between structural linting and semantic linting.
- [x] Decide when the linter should run.
- [ ] Decide how linter findings should be surfaced.
- [ ] Decide whether the linter is user-invoked, discrepancy-invoked, or both.

Current implementation status:
- structural linting now has an initial deterministic implementation in
  `src/monitor/lib/monitor_wiki_linter.py`
- unchecked semantic and workflow items below remain future work

## Structural Linting
- [x] Check for missing `INDEX.md` when a project wiki should exist.
- [x] Check for broken links between wiki pages.
- [ ] Check for referenced code paths that no longer exist.
- [x] Check for orphaned wiki pages not reachable from `INDEX.md`.
- [ ] Check for oversized or low-signal wiki pages.

## Semantic Linting
- [ ] Define what kinds of wiki claims should be compared against code.
- [ ] Define how to detect stale architecture, workflow, and ownership statements.
- [ ] Define when a wiki/code contradiction is considered material.
- [ ] Ensure semantic linting prefers code over stale wiki content.
- [ ] Ensure semantic linting recommends focused updates rather than broad rewrites.

## Architecture
- [ ] Decide whether to implement the linter as its own class or service.
- [ ] Decide where deterministic lint helpers should live.
- [ ] Decide whether the linter should have its own prompt template.
- [ ] Decide whether the linter should have its own model and reasoning configuration.
- [ ] Keep the linter separated from the normal code-writing path.

## Workflow and UX
- [ ] Decide whether the linter is exposed through a built-in command.
- [ ] Decide whether structural linting can be run without semantic linting.
- [ ] Decide what output shape is preferred for findings and recommendations.
- [ ] Decide whether wiki updates are only suggested or may be applied in a dedicated workflow.

## Testing
- [x] Add tests for structural lint checks.
- [x] Add tests for broken-link detection.
- [x] Add tests for orphaned-page detection.
- [x] Add tests for missing-file reference detection.
- [ ] Add tests for semantic conflict reporting behavior.
- [ ] Add tests for keeping the linter isolated from normal startup behavior.

## Documentation
- [ ] Document the purpose of the wiki-linter.
- [ ] Document when it should be run.
- [ ] Document the difference between structural and semantic linting.
- [ ] Document how findings should be interpreted.
- [ ] Document whether and how it can suggest wiki updates.

## Validation
- [ ] Verify structural linting is cheap and deterministic.
- [ ] Verify semantic linting is not excessively noisy.
- [ ] Verify code wins when code and wiki disagree.
- [ ] Verify the linter improves wiki reliability without becoming mandatory overhead.
