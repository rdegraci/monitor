# CHECKLIST_BENCHMARK_COMPARE_TOOL

Checklist for implementing and validating a dedicated benchmark run comparison
tool for `monitor_bench`.

## 0. Inputs and scope
- [x] Working plan exists (`PLAN_BENCHMARK_COMPARE_TOOL.md`).
- [x] Confirm the compare tool will consume the existing runner JSON format.
- [x] Confirm the first version is a developer utility, not a CI policy gate.
- [x] Confirm the first version is terminal-friendly text output only.

## 1. Core comparison behavior
- [x] Load two run JSON files successfully.
- [x] Compare overall summaries.
- [x] Compare per-task summaries.
- [x] Detect tasks present only in the before run.
- [x] Detect tasks present only in the after run.
- [x] Preserve handling of `metrics=None` samples.

## 2. Comparison semantics
- [x] Label clear improvements.
- [x] Label clear regressions.
- [x] Label mixed changes.
- [x] Label unchanged tasks when requested.
- [x] Keep semantics simple and explainable.

## 3. CLI
- [x] Support minimal invocation:
      `python -m benchmark.monitor_bench.compare before.json after.json`
- [x] Add `--only-regressions`.
- [x] Add `--only-improvements`.
- [x] Add `--task <name>`.
- [x] Add `--show-unchanged`.
- [x] Add `--sort-by pass|cost|tools|loops|duration`.

## 4. Output quality
- [x] Print overall summary first.
- [x] Show regressions clearly.
- [x] Show improvements clearly.
- [x] Show missing/new tasks clearly.
- [x] Keep output concise enough for terminal use.
- [x] Avoid overwhelming unchanged-task output by default.

## 5. Reuse and consistency
- [x] Reuse or mirror `report.py` aggregation logic.
- [x] Use task names as stable task identifiers.
- [x] Keep metric interpretation consistent with `report.py`.
- [x] Keep formatting conventions aligned with `inspect.py` / `report.py` where sensible.

## 6. Tests
- [x] Add unit tests for overall comparison rendering.
- [x] Add unit tests for per-task comparison.
- [x] Add unit tests for missing/new task detection.
- [x] Add unit tests for improvement/regression labeling.
- [x] Add unit tests for runs with missing metrics.
- [x] Add unit tests for filtering flags.

## 7. Optional later work
- [x] Add markdown output mode.
- [x] Add JSON diff output mode.
- [ ] Add per-tag comparison.
- [x] Add configurable delta thresholds.

## 8. Exit criteria
- [x] A developer can compare two run JSONs with a single command.
- [x] The tool makes it obvious which tasks improved or regressed.
- [x] The tool handles suite changes such as missing/new tasks gracefully.
- [x] The output is good enough to use in everyday benchmark workflows.
