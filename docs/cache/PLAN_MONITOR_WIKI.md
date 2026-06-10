# Monitor Wiki Plan

## Objective
Add support for a Monitor-managed `monitor-wiki/` area under appdir so Monitor
can maintain per-project LLM-oriented knowledge using repo-root-derived stable
slug directories.

## Scope
This feature should support:
- a top-level `monitor-wiki/` directory under appdir
- per-project subdirectories derived from the project repo root path
- lazy or purposeful creation of the top-level wiki directory
- creation of the project slug directory when wiki functionality is used
- governance guidance that distinguishes stable wiki content from transient
  working notes

## Design goals
- Keep wiki content separate from repo source trees by default.
- Use repo-root-derived path slugs instead of raw folder basenames.
- Avoid collisions between similarly named repositories in different paths.
- Keep wiki content compact and curated rather than mirroring source trees.
- Allow Monitor to use wiki content as a high-value context layer for code
  writing and modification tasks.

## Proposed structure
- `appdir/monitor-wiki/`
  - `<path-derived-stable-slug>/`
    - `INDEX.md`
    - optional stable project wiki pages

The slug should be based on the resolved repo root when Monitor starts inside a
repository. If Monitor starts outside a repo, fallback behavior can derive the
slug from the working directory path.

## Functional steps
1. Resolve appdir.
2. Resolve or detect the repo root for the current working directory.
3. Convert the repo root path into a stable slug.
4. Ensure `appdir/monitor-wiki/` exists when wiki functionality is needed.
5. Ensure `appdir/monitor-wiki/<slug>/` exists when project wiki access is
   needed.
6. Load relevant wiki content for the active project.
7. Update wiki content only when the change affects stable project knowledge.

## Resolved governance placement
- High-level monitor-wiki behavior now lives in `src/monitor/MONITOR.md` and is
  also reinforced by concise platform-level guidance in
  `src/monitor/lib/system_prompt.py`.
- Detailed project-specific knowledge continues to belong in per-project wiki
  content under `monitor-wiki/`.
- Working notes and design scratch space continue to belong outside the project
  wiki, such as in `docs/cache/`.

## Resolved implementation decisions

### Slug contract
- Use a path-derived stable slug.
- Use the canonicalized project identity path as the slug source.
- Normalize by lowercasing, replacing path separators and spaces with `-`,
  collapsing runs of non-alphanumeric characters to a single `-`, collapsing
  repeated `-`, and trimming leading or trailing `-`.
- Resolve symlinks before slug normalization.
- No slug length cap is required for the initial implementation.

### Project identity
- Use the nearest detected repo root when Monitor starts inside a git repo.
- Fall back to the current working directory when Monitor starts outside a git
  repo.
- Apply the same treatment to non-git projects through cwd fallback.
- Nested repos, submodules, and worktrees should map according to the nearest
  visible repo root from the startup path.

### Provisioning behavior
- Create `appdir/monitor-wiki/` lazily when wiki functionality actually needs
  it.
- Create the project slug directory on the first wiki-aware read or write
  operation for the active project.
- Empty slug directories are not preferred; provisioning should create the
  starter file when the project wiki directory is first created.
- Starter file creation should occur with project wiki provisioning.

### Minimum project wiki shape
- `INDEX.md` is the minimum required file for a newly provisioned project wiki.
- `INDEX.md` should use a compact structured starter template rather than being
  empty.
- Additional pages are optional and should be created only when needed.
### Existing wiki content
- A project wiki should be treated as substantive only when `INDEX.md` has been
  modified beyond the starter template.
- A newly provisioned wiki containing only the starter template should not be
  treated as existing project knowledge.

- No standard multi-file starter set is required for the initial
  implementation.

### Monitor integration
- Monitor should consult the project wiki for planning or editing in projects
  that already have wiki content, and for architectural, cross-cutting,
  convention-sensitive, or user-requested design guidance tasks.
- Wiki content should influence planning, editing, and review when relevant.
- Monitor should read `INDEX.md` first and load at most 2 additional wiki pages
  when the index points to them or the task clearly matches their topic.
- The initial implementation should not recursively auto-follow wiki links
  beyond the selected additional pages.
- Wiki guidance is advisory but preferred unless contradicted by code or newer
  project-local documentation.

### Wiki maintenance rules
- A code change should trigger wiki consideration only when it affects stable
  project knowledge.
- Monitor may suggest wiki updates automatically when warranted.
- Monitor should not modify wiki content automatically unless the user requests
  it or the workflow explicitly includes wiki maintenance.
- When wiki guidance materially conflicts with code or newer project-local
  documentation, Monitor should follow the code, mention the conflict, and may
  suggest a wiki update.
- The project wiki should not duplicate repo docs or grow into a file-by-file
  mirror.

### Metadata and lifecycle
- No metadata file is required for the initial implementation.
- The design should leave room for future metadata if lifecycle needs emerge.
- Stale or empty project wiki directories are acceptable short term but should
  remain a documented lifecycle concern.

## Current implementation status
- Added a shared helper module at `src/monitor/lib/monitor_wiki.py` for project
  identity resolution, slug derivation, configured wiki paths, and lazy wiki
  provisioning.
- Startup now freezes project wiki session context in `src/monitor/app.py`
  alongside runtime prompt path resolution.
- Prompt integration in `src/monitor/lib/system_prompt.py` now includes a
  bounded project wiki section when substantive wiki content exists.
- The current retrieval path reads `INDEX.md` first and includes up to 2
  additional referenced wiki pages with bounded excerpts.

## Suggested implementation areas
- appdir initialization or filesystem utility code
- startup context resolution for repo root detection
- a helper for path-to-slug conversion
- wiki path resolution helpers
- monitor guidance loading if wiki pages are later integrated into prompt
  assembly

## Risks
- creating empty project directories for repos that never use wiki content
- allowing wiki content to drift from the actual codebase
- letting the wiki expand into a low-signal mirror of the repository
- ambiguous behavior when Monitor starts outside a recognized repo

## Success criteria
- Monitor can derive a stable project wiki path from the startup location.
- `appdir/monitor-wiki/` is created automatically when needed.
- project wiki directories are created automatically when needed.
- the design avoids filename collisions across repos with the same basename.
- the wiki remains a compact, high-signal knowledge layer rather than a repo
  mirror.
