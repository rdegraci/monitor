# SPEC_BENCHMARK_COMPARE_TOOL

Behavior spec for a dedicated benchmark run comparison tool for
`monitor_bench`.

## Purpose

The compare tool exists to compare two benchmark run JSON files and summarize
whether the codebase improved, regressed, or stayed effectively unchanged.

It is a post-processing utility for developers, not part of benchmark execution
itself.

## Scope

This spec covers:
- accepted inputs,
- expected output categories,
- comparison behavior,
- filtering behavior,
- handling of missing/new tasks.

It does not define:
- statistical significance,
- transcript-level semantic comparison,
- charting,
- CI policy gates.

## Inputs

The tool accepts exactly two benchmark run JSON files:
- a before run,
- an after run.

These files must conform to the run format produced by
`benchmark.monitor_bench.runner`.

## Required comparisons

### 1. Overall comparison
The tool must compare overall values for:
- pass rate,
- average cost,
- average tool calls,
- average loop trips,
- average duration.

Optional later metrics may be added, but these are the core required signals.

### 2. Per-task comparison
The tool must compare tasks by task name.

For each task present in either run, the tool must compare:
- pass count / sample count,
- average cost,
- average tool calls,
- average loop trips,
- average duration.

### 3. Missing/new task detection
The tool must explicitly report when:
- a task exists only in the before run,
- a task exists only in the after run.

These tasks must not be silently ignored.

## Output behavior

### Default output
By default, the tool should:
- print an overall summary first,
- print meaningful task-level differences,
- include missing/new task information,
- omit unchanged tasks unless requested.

### Output categories
The tool must be able to classify task-level and overall differences as:
- improvement,
- regression,
- mixed,
- unchanged.

## Classification semantics

### Improvement
A comparison is an improvement when:
- pass rate increases, or
- pass rate stays the same and efficiency metrics improve without offsetting
  meaningful regressions.

### Regression
A comparison is a regression when:
- pass rate decreases, or
- pass rate stays the same and efficiency metrics worsen meaningfully.

### Mixed
A comparison is mixed when:
- some important metrics improve while others worsen.

### Unchanged
A comparison is unchanged when:
- values are materially the same,
- or differences are beneath the tool's chosen formatting/threshold rules.

## Handling of missing metrics

Some samples may have `metrics=None`.

The compare tool must preserve the same semantic treatment already used by the
benchmark reporting pipeline:
- pass/fail still counts toward pass rate,
- missing metrics do not silently become zero-valued metrics.

## CLI requirements

### Minimal invocation
The tool must support:

```bash
python -m benchmark.monitor_bench.compare before.json after.json
```

### Recommended filters
The tool should support:
- `--only-regressions`
- `--only-improvements`
- `--task <name>`
- `--show-unchanged`
- `--sort-by pass|cost|tools|loops|duration`

## Readability requirements

The output should be:
- terminal-friendly,
- easy to scan,
- concise by default,
- explicit about regressions.

It should not require a developer to inspect raw JSON to understand the main
result of the comparison.

## Extensibility expectations

The design should make it straightforward to add later:
- markdown output,
- JSON diff output,
- per-tag comparison,
- configurable thresholds.

These are extensions, not requirements for first-version conformance.

## Success criteria

A compare implementation conforms to this spec when a developer can:
- run one command with a before and after run,
- see whether overall behavior improved or regressed,
- identify which tasks changed most,
- identify which changes were correctness regressions vs efficiency regressions,
- identify tasks that were added or removed between runs.

## Bottom line

The benchmark compare tool's contract is simple:

> compare two run JSON files and make the behavior delta obvious.
