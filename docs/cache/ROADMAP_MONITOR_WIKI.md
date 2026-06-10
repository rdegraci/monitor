# Monitor Wiki Roadmap

## Phase 1: Project Identity and Storage Model
Define how Monitor maps a startup location to a project-specific wiki home.

### Deliverables
- appdir-level `monitor-wiki/` storage model
- repo-root-based project identity rules
- path-derived stable slug design
- canonical-path and symlink handling rules
- nested repo, submodule, and worktree rules
- non-repo fallback rules
- shared helper implementation for project identity and slug derivation
- startup wiring that freezes project wiki context for the session

### Outcome
Monitor has a deterministic and collision-resistant way to locate the wiki for
an active project.

### Status
- Implemented in `src/monitor/lib/monitor_wiki.py` and wired from
  `src/monitor/app.py`.

## Phase 2: Filesystem Provisioning
Add lazy automatic creation of the top-level wiki directory and project wiki
subdirectories.

### Deliverables
- lazy automatic creation of `appdir/monitor-wiki/`
- creation of `appdir/monitor-wiki/<slug>/` on the first wiki-aware read or
  write operation
- graceful handling of creation failures
- creation of `INDEX.md` as the initial starter file
- decision to defer metadata file creation in the initial implementation
- configured project wiki provisioning helpers for first wiki-aware use

### Outcome
Users do not need manual setup before Monitor can use project wiki content.

### Status
- Implemented via lazy provisioning helpers in `src/monitor/lib/monitor_wiki.py`.

## Phase 3: Governance Model
Define what the monitor-wiki is for, what it should not become, and where that
policy should live.

### Deliverables
- governance guidance for stable wiki content
- distinction between monitor-wiki content and transient working notes
- anti-bloat rules that prevent source-tree mirroring
- guidance for when code changes should trigger wiki updates
- definition of what counts as substantive wiki content
- minimum project wiki file structure guidance centered on `INDEX.md`
- lifecycle guidance acknowledging deferred metadata support
- governance placement split between high-level guidance in `MONITOR.md` and
  detailed durable knowledge in per-project wiki content
- concise platform-level reinforcement in `src/monitor/lib/system_prompt.py`

### Outcome
The wiki remains a compact, curated knowledge layer rather than expanding into a
second copy of the repository, and its governance model is anchored in the
packaged prompt guidance as well as in the wiki design docs.

## Phase 4: Retrieval and Workflow Integration
Integrate project wiki awareness into Monitor workflows.

### Deliverables
- rules for when Monitor should consult the project wiki
- rules for how wiki content should guide planning, editing, and review
- `INDEX.md` as the primary retrieval entry point
- default limit of 2 additional wiki pages with no recursive auto-follow in v1
- conflict-handling guidance when wiki and code disagree materially
- boundaries that prevent the global prompt from becoming overloaded
- bounded prompt integration for `INDEX.md` and up to 2 referenced pages

### Outcome
Monitor can use project wiki knowledge to improve code-writing and code-modify
workflows without turning the wiki into mandatory overhead.

### Status
- Partially implemented in `src/monitor/lib/system_prompt.py` with bounded
  `INDEX.md` excerpts and up to 2 additional referenced page excerpts.

## Phase 5: Hardening and Validation
Validate path mapping, creation behavior, and failure handling.

### Deliverables
- test coverage for slug derivation and path stability
- test coverage for directory creation behavior
- test coverage for startup inside nested repo directories
- test coverage for non-repo working directories
- verification of acceptable operational behavior when filesystem access fails

### Outcome
The monitor-wiki feature is reliable, predictable, and maintainable.
