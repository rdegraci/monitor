# Monitor Wiki Specification

## Purpose
Define the default behavior for Monitor-managed project wiki storage under
appdir so the feature can be implemented consistently.

## Project Identity
- When Monitor starts inside a git repository, the active project identity is
  the nearest detected repo root.
- When Monitor starts outside a git repository, the active project identity
  falls back to the current working directory.
- The resolved project identity path is the input for wiki path derivation.

## Canonical Path Handling
- The project identity path should be canonicalized before slug derivation.
- Symlinks should be resolved before the slug is produced.
- Canonicalization should prevent duplicate wiki directories for the same
  project reached through different equivalent paths.

## Slug Derivation
The project wiki directory name should be a path-derived stable slug.

### Normalization rules
- convert the canonicalized source path to lowercase
- replace path separators with `-`
- replace spaces with `-`
- replace any run of non-alphanumeric characters with a single `-`
- collapse repeated `-`
- trim leading and trailing `-`

### Expected behavior
- similarly named repositories in different paths must not collide
- nested working directories inside one repository must map to the same slug
- non-repo working directories must still produce deterministic slugs

## Nested Repositories, Submodules, and Worktrees
- Project identity should use the nearest detected repo root from the startup
  directory.
- Starting inside a nested repo or submodule should map to that nested repo's
  wiki rather than the outer repo's wiki.
- Worktree behavior should follow the repo root visible from the startup path.

## Filesystem Provisioning
### Top-level wiki directory
- `appdir/monitor-wiki/` should be created lazily.
- The directory should be created the first time wiki functionality actually
  needs it.
- Startup alone should not create the top-level wiki directory unless wiki use
  is in progress.

### Project wiki directory
- `appdir/monitor-wiki/<slug>/` should be created on the first wiki-aware read
  or write operation for the active project.
- Project startup alone should not create the slug directory if no wiki-aware
  operation occurs.

## Minimum Project Wiki Structure
When a project wiki directory is first created, Monitor should create:
- `INDEX.md`

`INDEX.md` should contain a compact structured starter template rather than
being empty.

No additional project wiki pages are required by default.
Optional pages such as `ARCHITECTURE.md`, `CONVENTIONS.md`, `TESTING.md`, and
`PITFALLS.md` may be added later when needed.

## Metadata
- A metadata file is not required for the initial implementation.
## Existing Wiki Content
- A project is considered to have existing wiki content only when `INDEX.md`
  exists and has been meaningfully modified beyond the auto-created starter
  template.
- A provisioned wiki directory containing only the starter template does not yet
  count as substantive project wiki content.

- The implementation should leave room for a future metadata file if lifecycle
  or migration needs emerge.

## Retrieval Behavior
- `INDEX.md` is the primary retrieval entry point for a project wiki.
- Monitor should consult `INDEX.md` first when using wiki content.
- Monitor should read at most 2 additional wiki pages by default.
- Additional wiki pages should be consulted only when:
  - `INDEX.md` points to them, or
  - the task clearly matches their topic.
- The initial implementation should not recursively follow links beyond the
  selected additional pages.

## Workflow Integration
By default, Monitor should consult the project wiki:
- before planning or editing in a project that already has wiki content
- when the task is architectural, cross-cutting, or convention-sensitive
- when the user requests design, refactor, or project-guidance help

Monitor does not need to load wiki content for every trivial or obviously local
change.

## Authority Model
- Project wiki guidance is advisory but preferred.
- Source code and newer project-local documentation take precedence when they
  contradict the wiki.
- When a conflict materially affects the current task, Monitor should mention
  the conflict and may suggest that the wiki be updated.
- The wiki should help narrow and improve code inspection, not replace source
  inspection.

## Governance Placement
- High-level monitor-wiki behavior should live in the packaged `MONITOR.md`
  and may be reinforced by concise platform-level guidance in
  `src/monitor/lib/system_prompt.py`.
- Detailed project-specific knowledge belongs in per-project wiki content under
  `monitor-wiki/`.
- Repo-local documentation remains the authoritative home for project docs that
  should travel with the repository.
- `docs/cache/` remains the home for transient planning notes, checklists,
  roadmaps, and design scratch material rather than durable per-project wiki
  guidance.

## Wiki Maintenance Policy
Monitor should not update the project wiki after every code change.

Wiki updates are appropriate when a change affects stable project knowledge,
including:
- architecture
- coding conventions
- important subsystem boundaries
- recurring workflows
- important pitfalls or gotchas
- other durable project operating knowledge

## Automatic Wiki Updates
- Monitor may suggest wiki updates when they appear warranted.
- Monitor should not automatically modify wiki content unless the user requests
  it or the workflow explicitly includes wiki maintenance.

## Anti-Bloat Rules
The monitor-wiki must remain a compact, high-signal knowledge layer.

It should not become:
- a mirror of the source tree
- one page per source file by default
- a large generated inventory of every symbol or file

Preferred page granularity:
- repository overview pages
- subsystem pages
- workflow pages
- convention pages
- pitfalls or gotchas pages

## Failure Handling
If Monitor cannot create the top-level wiki directory or the project wiki
subdirectory:
- surface a clear message
- do not crash unrelated code workflows solely because wiki provisioning failed
- treat wiki support as unavailable for that operation or session when needed

## Implementation Findings

### Existing startup integration point
- `src/monitor/app.py` already snapshots the startup working directory with
  `configure_runtime_prompt_paths(os.getcwd())`.
- This is the best existing point for capturing project identity once at
  startup and freezing it for the session.

### Existing appdir integration point
- `src/monitor/lib/system_prompt.py` already owns appdir-backed runtime files
  such as `MONITOR.md` and `MONITOR_CONVENTIONS.md` via
  `appdirs.user_config_dir("monitor")`.
- The helper functions `_seed_runtime_file()` and `_read_runtime_file()` already
  demonstrate lazy appdir directory creation and seeded file creation.

### Existing project override integration point
- `src/monitor/lib/system_prompt.py` already resolves project-local prompt-file
  overrides with `configure_runtime_prompt_paths(startup_cwd)`.
- That function is the closest existing abstraction for frozen startup project
  context and is a strong conceptual integration point for future wiki context
  resolution.

### Existing repo-root detection example
- `src/monitor/lib/bulk_replace.py` contains `_repo_root()`, which walks upward
  from `os.getcwd()` using `os.path.realpath()` and returns the nearest
  directory containing `.git`.
- This is the best current reference implementation for repo-root-based project
  identity behavior.

## Implementation Recommendations

### Shared helper module
Monitor should introduce a shared helper module under `src/monitor/lib/` for
monitor-wiki path and provisioning behavior.

That module should own:
- project identity resolution
- nearest repo-root detection
- non-repo fallback to the startup working directory
- canonical path handling
- slug derivation
- monitor-wiki root path resolution
- project wiki directory resolution
- lazy provisioning of wiki directories and `INDEX.md`

This behavior should not be duplicated ad hoc across unrelated modules.

### Startup wiring
- `src/monitor/app.py` should remain the place where startup cwd is captured.
- Startup should call into the shared helper to resolve and freeze project wiki
  context for the session when that feature is implemented.
- `app.py` should stay thin and should not directly own slug derivation or wiki
  directory creation details.
- This is now implemented by wiring startup through
  `monitor_wiki.configure_project_wiki_paths(startup_cwd)`.

### Prompt integration boundary
- `src/monitor/lib/system_prompt.py` is the likely place for later monitor-wiki
  retrieval and prompt integration.
- It should not become the owner of all monitor-wiki path logic, slugging, or
  provisioning details.
- Prompt integration should follow path/provisioning work rather than being part
  of the first implementation step.
- The current implementation now includes bounded prompt integration that reads
  `INDEX.md` first and includes up to 2 additional referenced pages when
  substantive wiki content exists.

### Reuse existing repo-root logic
- The repo-root detection behavior currently in `bulk_replace._repo_root()`
  should be reused or extracted into shared logic rather than reimplemented in
  multiple places.

## Recommended Phased Implementation

### Phase 1: Project identity and provisioning
Implement:
- project identity resolution
- path canonicalization
- slug derivation
- lazy creation of `appdir/monitor-wiki/`
- lazy creation of `appdir/monitor-wiki/<slug>/`
- creation of `INDEX.md`

Likely files:
- `src/monitor/app.py`
- a new shared helper module under `src/monitor/lib/`
- targeted tests for identity and provisioning behavior

### Phase 2: Wiki retrieval and prompt usage
Implement:
- reading `INDEX.md`
- controlled loading of additional wiki pages when needed
- prompt integration using the resolved project wiki context

Likely files:
- `src/monitor/lib/system_prompt.py`
- prompt-related tests

### Phase 3: Wiki maintenance assistance
Implement:
- suggestion or workflow support for updating stable wiki knowledge after
  relevant code changes

This phase should come after path resolution and retrieval behavior are proven
stable.

## Recommended v1 Summary
- use nearest repo root, else current working directory
- canonicalize the project path before slug derivation
- use a path-derived stable slug
- lazily create `appdir/monitor-wiki/`
- create `appdir/monitor-wiki/<slug>/` when wiki functionality is actually used
- auto-create only `INDEX.md`
- use `INDEX.md` as the primary wiki entry point
- treat wiki guidance as advisory but preferred unless contradicted by code
- suggest wiki updates for stable knowledge changes rather than applying them
  automatically
- do not let the project wiki become a repo mirror
