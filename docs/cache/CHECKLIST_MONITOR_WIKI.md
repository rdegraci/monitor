# Monitor Wiki Checklist

## Discovery and Design
- [x] Confirm appdir location and how Monitor resolves it today.
- [x] Identify where startup resolves the current project context.
- [x] Identify how repo root detection should work at startup.
- [x] Define the path-derived stable slug normalization rules.
- [x] Confirm fallback behavior when Monitor starts outside a repo.
- [x] Decide whether slug derivation uses canonicalized paths.
- [x] Decide how nested repos, submodules, and worktrees are handled.
- [x] Decide whether slug length limits or truncation rules are needed.

## Filesystem Behavior
- [x] Add support for creating `appdir/monitor-wiki/` automatically.
- [x] Add support for creating `appdir/monitor-wiki/<slug>/` automatically.
- [x] Decide whether wiki directories are created lazily or eagerly.
- [x] Decide the exact lazy provisioning trigger.
- [x] Decide whether starter files such as `INDEX.md` are auto-created.
- [x] Decide whether empty slug directories are acceptable.
- [x] Decide whether a metadata file is created with the slug directory.
- [ ] Ensure filesystem failures are surfaced clearly and handled gracefully.

## Wiki Path Resolution
- [x] Implement repo-root-based slug derivation.
- [x] Ensure similarly named repos in different paths do not collide.
- [x] Ensure startup from nested directories inside one repo maps to the same slug.
- [x] Ensure non-repo working directories still produce stable behavior.

## Governance and Content Boundaries
- [x] Define what belongs in `monitor-wiki/` versus repo-local docs.
- [x] Define what belongs in the wiki versus `docs/cache/` working notes.
- [x] Define when a code change should also update the wiki.
- [x] Define whether Monitor may propose wiki updates automatically.
- [x] Define what counts as existing substantive wiki content.
- [x] Keep wiki pages compact and subsystem-oriented rather than file-oriented.
- [x] Define anti-bloat rules that prevent source-tree mirroring.
- [x] Decide where the governance spec lives, such as `MONITOR.md`.

## Prompt and Workflow Integration
- [x] Define when Monitor should consult project wiki content.
- [x] Define whether wiki content should influence planning, editing, review, or all code workflows.
- [x] Define whether Monitor should read only `INDEX.md` first or load multiple wiki pages directly.
- [x] Define default retrieval limits for additional wiki pages.
- [x] Define whether wiki guidance is advisory or preferred unless contradicted by code.
- [x] Define how material wiki/code conflicts should be surfaced.
- [x] Define whether Monitor should update wiki content automatically or only when instructed.
- [x] Avoid overloading the global prompt with detailed wiki-maintenance policy.

## Testing
- [x] Add tests for top-level wiki directory creation.
- [x] Add tests for project slug directory creation.
- [x] Add tests for repo-root-based slug stability.
- [x] Add tests for nested working directory mapping.
- [x] Add tests for non-repo fallback behavior.
- [x] Add tests for same-basename repos in different paths.
- [ ] Add tests for symlink or canonical-path slug behavior if supported.
- [ ] Add tests for safe handling of filesystem creation failures.

## Documentation
- [x] Document monitor-wiki purpose and structure.
- [x] Document slug derivation rules.
- [x] Document repo-root and non-repo path resolution behavior.
- [x] Document lazy versus eager creation behavior.
- [x] Document governance and anti-bloat rules.
- [x] Document the minimum project wiki file structure.

## Validation
- [x] Verify wiki paths are deterministic across sessions.
- [x] Verify wiki directories are not duplicated for nested repo paths.
- [x] Verify same-basename repos map to distinct wiki paths.
- [x] Verify wiki creation does not break normal startup behavior.
- [x] Verify empty-directory sprawl is acceptable or mitigated by design.
- [x] Verify wiki guidance and code remain consistent when both exist.
