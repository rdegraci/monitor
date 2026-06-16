# PLAN_BENCHMARK_COMPARE_TOOL

Working plan for a dedicated benchmark run comparison tool for `monitor_bench`.

## Goal

Add a simple post-processing utility that compares two benchmark run JSON files
and makes it easy to answer:

- what improved,
- what regressed,
- what stayed the same,
- which tasks are missing or newly added.

This tool is intended to remove the current manual work of opening two run JSON
files and eyeballing differences in pass rate, cost, tool calls, and loopiness.

## Motivation

The existing benchmark workflow already provides:
- raw run JSON from `runner.py`,
- aggregate markdown reporting from `report.py`,
- per-run debugging from `inspect.py`.

What is still missing is a direct answer to:

> Did the codebase get better or worse after this change?

The compare tool fills that gap by turning two benchmark runs into a concise
human-readable delta report.

## Non-goals

The first version does **not** need to provide:
- statistical significance testing,
- transcript-level semantic diffing,
- charting or visualization,
- provider/model quality scoring beyond what is already in the run JSON,
- CI policy enforcement.

This should start as a lightweight developer utility.

## Proposed module

- `benchmark/monitor_bench/compare.py`

This follows the same pattern as:
- `runner.py`
- `report.py`
- `inspect.py`

## Inputs

Two benchmark run JSON files:

```bash
python -m benchmark.monitor_bench.compare before.json after.json
```

The files are expected to conform to the run format already produced by
`benchmark.monitor_bench.runner`.

## Output

A terminal-friendly comparison report.

### Primary output sections
- overall summary,
- regressions,
- improvements,
- mixed changes,
- missing/new tasks.

Optional later additions could include:
- markdown output,
- machine-readable diff JSON,
- per-tag comparison sections.

## Metrics to compare

### Overall
For the whole run, compare:
- pass rate,
- average cost,
- average tool calls,
- average loop trips,
- average duration,
- optionally average tokens.

### Per task
For each task present in either run, compare:
- pass count / sample count,
- average cost,
- average tool calls,
- average loop trips,
- average duration,
- optionally average tokens.

### Optional per tag
A first version may omit per-tag comparison, but the design should make it easy
to add later using the same aggregation logic as `report.py`.

## Comparison semantics

### Clear improvement
A task or overall run is clearly improved when:
- pass rate increases, or
- pass rate stays the same and one or more efficiency metrics improve without
  offsetting regressions.

Examples:
- same pass rate, lower cost,
- same pass rate, fewer tool calls,
- same pass rate, fewer loop trips,
- same pass rate, shorter runtime.

### Clear regression
A task or overall run is clearly worse when:
- pass rate decreases, or
- pass rate stays the same and one or more efficiency metrics worsen
  meaningfully.

Examples:
- same pass rate, much higher tool-call count,
- same pass rate, more loop trips,
- same pass rate, much higher cost.

### Mixed change
Use a mixed label when some metrics improve and others worsen.

Examples:
- pass rate improves but cost rises,
- tool calls go down but duration goes up,
- cost drops but loop trips increase.

### Unchanged
Use unchanged when values are the same or differences are negligible according
to simple formatting/threshold rules.

## Missing/new task handling

The tool should explicitly detect when a task exists only in one run.

Examples:
- task present in `before` but not `after`,
- task present in `after` but not `before`.

This is important because benchmark suites will evolve over time and task
absence should not be silently ignored.

## CLI shape

### Minimal invocation
```bash
python -m benchmark.monitor_bench.compare before.json after.json
```

### Recommended flags
- `--only-regressions`
- `--only-improvements`
- `--task <name>`
- `--show-unchanged`
- `--sort-by pass|cost|tools|loops|duration`

### Optional future flags
- `--format markdown`
- `--format json`
- `--cost-delta-threshold <float>`
- `--tool-delta-threshold <float>`

## Recommended default behavior

By default, the tool should:
- print overall comparison first,
- show regressions and improvements,
- omit unchanged tasks unless requested,
- include missing/new tasks,
- keep output concise and readable in terminal.

## Example output shape

```text
# monitor_bench compare

Before: results/before.json
After:  results/after.json

Overall
-------
Pass rate:      7/10 (70%) -> 9/10 (90%)   [IMPROVED]
Avg cost:       $0.0112    -> $0.0097      [IMPROVED]
Avg tool calls: 12.4       -> 8.9          [IMPROVED]
Avg loops:      0.5        -> 0.0          [IMPROVED]
Avg duration:   17.8s      -> 16.4s        [IMPROVED]

Improvements
------------
seeded_bugfix_multistep
  Pass:   2/3 -> 3/3
  Tools:  11.7 -> 8.3
  Loops:  0.3 -> 0.0

plan_then_execute_refactor
  Pass:   1/3 -> 3/3
  Cost:   $0.015 -> $0.012

Regressions
-----------
(none)

Missing/new tasks
-----------------
repo_server_surface: present only in BEFORE
tool_efficiency_stress_readflow: present only in AFTER
```

## Implementation approach

### Reuse existing aggregation logic where possible
`report.py` already computes:
- overall summaries,
- per-task summaries,
- per-tag summaries.

The compare tool should reuse or mirror that logic rather than recomputing the
raw metrics differently.

### Match by task name
Task comparison should be keyed by task name.

This is simple, stable, and consistent with how benchmark tasks are identified
throughout the current harness.

### Handle missing metrics safely
Some samples may have `metrics=None`.

The compare tool should preserve the same reporting semantics already used by
`report.py`:
- failed/crashed samples still count toward pass rate,
- missing metrics do not silently become zero-cost or zero-tool-call samples.

## Suggested implementation phases

### Phase 1 — Core compare
Implement:
- overall comparison,
- per-task comparison,
- missing/new task detection,
- terminal-friendly output.

This is enough to make the tool useful immediately.

### Phase 2 — Filtering and quality-of-life flags
Add:
- `--only-regressions`,
- `--only-improvements`,
- `--task`,
- `--show-unchanged`,
- `--sort-by`.

### Phase 3 — Optional richer outputs
Add later if useful:
- markdown mode,
- JSON diff mode,
- per-tag comparison,
- threshold flags.

## Testing strategy

Tests should cover:
- overall comparison rendering,
- task matching between runs,
- regression/improvement labeling,
- missing/new task detection,
- handling of runs with missing metrics,
- filtering behavior for optional CLI flags.

The tests should follow the existing style in:
- `tests/benchmark/test_runner.py`
- `tests/benchmark/test_report.py`
- `tests/benchmark/test_inspect.py`

## Expected difficulty

This feature should be:
- low complexity,
- low risk,
- high leverage.

Most of the required work is formatting and comparison logic rather than deep
benchmark or Monitor runtime behavior.

## Success criteria

The compare tool is successful when a developer can run:

```bash
python -m benchmark.monitor_bench.compare before.json after.json
```

and quickly understand:
- whether the codebase improved or degraded,
- which benchmark tasks changed most,
- whether those changes were correctness regressions or efficiency regressions,
- whether any benchmark tasks disappeared or were newly added.

## Bottom line

A benchmark compare tool is an easy, high-value addition to the current
benchmarking workflow. It completes the loop from:
- run benchmarks,
- inspect a single run,
- summarize a single run,

to:
- compare two runs and decide whether the codebase got better or worse.
