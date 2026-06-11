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

### Semantic linting
- compare stable wiki claims against the current codebase
- detect likely stale ownership, workflow, or architecture statements
- identify wiki/code contradictions that would materially affect coding tasks
- suggest focused updates rather than broad rewrites

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
- whether the linter should be exposed as a built-in command, internal workflow,
  or both
- whether structural and semantic linting should be separately invocable
- whether semantic linting should use a dedicated model configuration
- what output format is most useful for discrepancy reports
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
  broken references, and orphaned markdown pages
- no built-in command or semantic drift workflow has been added yet
