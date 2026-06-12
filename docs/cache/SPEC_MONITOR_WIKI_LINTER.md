# Monitor Wiki Linter Specification

## Purpose
Define a separate linter capability for monitor-wiki content so Monitor can
check project wiki integrity and likely staleness without overloading the main
coding workflow.

## Role
The wiki-linter is a maintenance and drift-detection tool.
It is distinct from:
- monitor-wiki provisioning and retrieval
- normal code-writing and code-modification workflows
- automatic wiki maintenance on every change

## Execution Model
- The wiki-linter should not run on every startup.
- The wiki-linter should not run on every code change.
- The wiki-linter should run only when explicitly requested or when a material
  discrepancy is detected and a lint pass is warranted.
- High-level wiki-linter behavior should live in the packaged `MONITOR.md`
  and may be reinforced by concise platform-level guidance in
  `src/monitor/lib/system_prompt.py`.

## Linting Modes
### Structural linting
Structural linting should use deterministic checks where possible.

It should validate:
- whether `INDEX.md` exists when expected
- whether linked wiki pages exist
- whether referenced code paths still exist when applicable
- whether wiki pages are orphaned from `INDEX.md`
- whether wiki pages appear excessively large
- whether wiki pages appear low-signal

### Semantic linting
Semantic linting may use an LLM-assisted workflow.

It should validate:

#### Semantic linting v1 scope
Semantic linting v1 should stay intentionally narrow.

It should focus on claims that are both stable and materially useful to coding
work, including:
- architecture claims about major subsystem boundaries, ownership of
  responsibilities, or where key behaviors live
- workflow claims about how code is built, tested, or reviewed when those
  claims affect developer actions
- ownership or routing claims only when they affect where a developer should
  look or which subsystem should be changed

Semantic linting v1 should avoid broad interpretation of:
- stylistic prose quality
- aspirational statements that are not framed as current fact
- minor wording drift that does not change coding decisions
- broad completeness judgments about whether a page says enough

#### Material contradiction standard
A semantic contradiction should be considered material only when a stale or
incorrect wiki claim would likely mislead a developer about:
- where to make a change
- which subsystem owns a behavior
- how to run or validate a workflow
- which project-local document or code path is authoritative

The linter should not report semantic findings for small wording differences,
benign simplifications, or claims that cannot be grounded in current code or
newer project-local documentation.

#### Semantic evidence expectations
Semantic linting should prefer findings backed by explicit evidence.

A semantic finding should ideally include:
- the wiki claim being evaluated
- the code path or newer project-local document that contradicts it
- a short explanation of why the contradiction matters to coding work
- a narrow recommendation for updating only the affected wiki text

When evidence is weak, ambiguous, or spread across too much of the codebase,
semantic linting v1 should decline to report a finding rather than speculate.
- whether stable architecture claims still match the codebase
- whether workflow or ownership statements appear stale
- whether wiki guidance materially contradicts the current code or newer docs
- whether update recommendations can be narrowly scoped

## Authority Model
- Code and newer project-local documentation take precedence over the wiki.

### Semantic finding shape for v1
Semantic findings may extend the structural finding shape with additional
semantic fields when needed.

In addition to stable fields such as `kind`, `severity`, `page`, `path`,
`message`, and `suggestion`, semantic findings should prefer fields such as:
- `claim` for the wiki statement being evaluated
- `evidence` for the contradicting code path or newer project-local document
- `impact` for why the contradiction matters to coding work

Semantic findings should remain minimal and stable rather than returning long
free-form analysis blobs.
- The linter should treat wiki/code conflicts as signs of likely wiki staleness.
- The linter should prioritize detecting meaningful drift over stylistic rewrite suggestions.

## Findings and Output
- Findings should be focused and actionable.
- Structural issues should be reported separately from semantic issues when possible.
- Material contradictions should identify why they matter to coding tasks.
- Recommendations should favor minimal, targeted wiki updates.
- Structured findings should prefer stable fields such as `kind`, `severity`,
  `page`, `path`, `message`, and `suggestion`.
- A human-readable report format should summarize PASS/FAIL status, project
  path, per-severity sections, and actionable suggestions.
- A simple invocation helper may return both structured lint output and the
  formatted report together.
- A built-in `:wiki_lint` command surfaces the formatted report directly to
  the user while preserving the structured result internally.
- `:wiki_lint` supports explicit `structural`, `semantic`, and `all` modes and
  defaults to structural mode when no argument is provided.
- Semantic mode currently implements a narrow semantic v1 check for stale
  location/path claims in wiki text.
- The current semantic v1 emits findings only for claim-bearing lines that use
  phrases such as `lives in`, `implemented in`, `defined in`, or
  `authoritative implementation` and cite repo-relative paths that no longer
  exist.
- Latest wiki-lint results may be stored in-process with stable finding ids so
  explicit follow-up workflows can target one finding at a time.

## Component Isolation
- The wiki-linter should be implemented as a separate component from the main
  coding workflow.
- A dedicated linter module, service, or class is preferred.
- The initial design should keep deterministic linting and semantic linting
  conceptually separable.

## Prompt and Configuration
- The semantic wiki-linter may use a dedicated prompt template.
- The semantic wiki-linter may use its own model and reasoning configuration.
- Any dedicated configuration should remain isolated from the default coding
  assistant configuration.

## Update Behavior
- The wiki-linter may recommend wiki updates.
- The wiki-linter should not automatically rewrite wiki content unless invoked
  through a dedicated workflow that explicitly allows that behavior.

## Non-Goals for Initial Design
- always-on background linting
- mandatory linting before normal edits
- broad stylistic rewriting of wiki content
- replacing source inspection with wiki validation

## Recommended v1 Summary
- keep the wiki-linter separate from monitor-wiki provisioning
- support deterministic structural checks first
- support optional LLM-assisted semantic drift detection later
- run only on demand or when discrepancy-triggered
- prefer code over stale wiki content
- allow separate prompt and model configuration for semantic linting if needed

## Current implementation status
- a structural wiki-linter v1 now exists in
  `src/monitor/lib/monitor_wiki_linter.py`
- the implemented deterministic checks currently cover:
  - missing `INDEX.md`
  - broken wiki-page references from `INDEX.md`
  - missing repo-relative path references such as `src/...`, `tests/...`, and
    `docs/...` mentioned from wiki markdown pages
  - oversized markdown pages based on deterministic size thresholds
  - low-signal markdown pages based on deterministic heading/reference/list
    heuristics
  - orphaned markdown pages not referenced from `INDEX.md`
- semantic drift detection remains future work
