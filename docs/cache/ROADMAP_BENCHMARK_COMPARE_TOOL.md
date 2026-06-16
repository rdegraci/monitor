# ROADMAP_BENCHMARK_COMPARE_TOOL

Roadmap for adding a dedicated benchmark run comparison tool to
`monitor_bench`.

## Goal

Make it easy to compare two benchmark runs and determine whether the codebase
improved or degraded without manually inspecting raw JSON files.

## Phase 1 — Core comparison
**Goal:** Make the tool immediately useful for day-to-day development.

Implement:
- loading two run JSON files,
- overall comparison,
- per-task comparison,
- missing/new task detection,
- terminal-friendly text output.

**Why this matters:**
This is the minimum needed to answer the main developer question:
"Did my change make Monitor better or worse?"

**Exit criteria:**
- developers can compare two runs from the command line,
- regressions and improvements are visible without manual JSON spelunking.

## Phase 2 — Filtering and quality-of-life flags
**Goal:** Make the tool practical for repeated use.

Add:
- `--only-regressions`,
- `--only-improvements`,
- `--task <name>`,
- `--show-unchanged`,
- `--sort-by`.

**Why this matters:**
Developers often care about one task, or only regressions, or want to reduce
noise from unchanged tasks.

**Exit criteria:**
- the most common compare workflows can be done without manual post-filtering.

## Phase 3 — Formatting and output growth
**Goal:** Improve usefulness in PRs and automation.

Potential additions:
- markdown output,
- machine-readable JSON diff output,
- richer formatting of mixed changes.

**Why this matters:**
Once the terminal compare is useful, markdown and JSON outputs make the tool
more useful in review and automation contexts.

**Exit criteria:**
- comparison results can be pasted into PRs or consumed by other tooling.

## Phase 4 — Richer comparison semantics
**Goal:** Improve comparison quality without overcomplicating the first version.

Potential additions:
- per-tag comparison,
- configurable delta thresholds,
- better categorization of mixed changes,
- optional emphasis on pass-rate regressions over efficiency regressions.

**Why this matters:**
Some workflows need a more opinionated or more flexible interpretation of what
counts as improvement or degradation.

**Exit criteria:**
- developers can tune the tool to highlight the differences they care about most.

## Phase 5 — Workflow integration
**Goal:** Make compare a routine part of benchmark usage.

Potential follow-ups:
- README examples,
- baseline-compare workflow documentation,
- optional CI or local wrapper commands,
- consistency with benchmark inspection and reporting docs.

**Why this matters:**
A good compare tool is most valuable when it becomes part of normal engineering
behavior rather than a one-off utility.

**Exit criteria:**
- benchmark users know when and how to run compare,
- compare output becomes part of before/after evaluation norms.

## Priorities

### Quick wins
- Phase 1 core compare,
- basic text output,
- missing/new task detection.

### Medium-term improvements
- filtering flags,
- markdown output,
- per-tag comparison,
- configurable thresholds.

### Highest-value additions
- reliable overall and per-task delta summaries,
- explicit regression highlighting,
- low-noise compare output that makes behavior changes obvious.

## Bottom line

The compare tool should start small and immediately useful. A clean first
version that compares two run JSON files and highlights regressions and
improvements is more valuable than a feature-rich tool that takes longer to land
or becomes hard to interpret.
