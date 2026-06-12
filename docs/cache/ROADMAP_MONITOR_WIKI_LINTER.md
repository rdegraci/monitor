# Monitor Wiki Linter Roadmap

## Phase 1: Role and Scope Definition
Define the purpose, boundaries, and governance placement of the wiki-linter.

### Deliverables
- linter purpose separate from monitor-wiki provisioning
- distinction between structural and semantic linting
- execution model for when linting should run
- high-level linter guidance captured in `MONITOR.md`
- concise platform-level reinforcement in `src/monitor/lib/system_prompt.py`

### Outcome
The wiki-linter has a clear role as a maintenance and drift-detection tool, and
its high-level behavior is anchored in packaged prompt guidance.

### Status
- Role and scope are documented.
- A structural deterministic implementation now exists in
  `src/monitor/lib/monitor_wiki_linter.py`.

## Phase 2: Structural Linting
Implement cheap deterministic checks for monitor-wiki health.

### Deliverables
- missing-index detection
- broken-link detection
- orphaned-page detection
- missing referenced file detection
- oversized-page heuristics

### Outcome
Basic monitor-wiki integrity issues can be detected without LLM involvement.

### Status
- Implemented for missing `INDEX.md`, broken wiki-page references, missing
  repo-relative path references, oversized markdown pages, low-signal
  markdown pages, and orphaned markdown pages.

## Phase 3: Semantic Drift Detection
Add targeted LLM-assisted checking for wiki/code contradictions.

### Deliverables
- semantic comparison rules for stable wiki claims
- material-conflict reporting
- focused update recommendations
- preference for code over stale wiki content

### Outcome
Monitor can detect meaningful wiki staleness when deterministic checks are not enough.

## Phase 4: Component Isolation and Configuration
Separate the linter from the normal coding flow.

### Deliverables
- dedicated linter module or class
- optional dedicated prompt template
- optional dedicated model and reasoning configuration
- workflow isolation from normal startup and edit paths

### Outcome
The linter can evolve independently without overloading the main assistant behavior.

## Phase 5: UX and Hardening
Define how the linter is invoked and how users consume its findings.

### Deliverables
- explicit invocation model
- report format for findings
- tests for structural and semantic behavior
- clear documentation for usage and interpretation

### Outcome
The wiki-linter is useful, understandable, and optional rather than intrusive.

### Status
- Structured finding output and a human-readable report formatter now exist.
- Explicit invocation and semantic UX remain future work.
