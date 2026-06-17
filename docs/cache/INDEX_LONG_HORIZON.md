# INDEX_LONG_HORIZON

Navigation index for the long-horizon documentation set in Monitor.

This file is a lightweight entry point for the long-horizon docs so operators
and contributors can quickly find the right document for planning, operating,
benchmarking, or extending long-horizon support.

## Recommended reading order

If you are new to the long-horizon docs, read in this order:

1. `docs/cache/SPEC_LONG_HORIZON.md`
   - the working behavior contract for long-horizon support.
2. `docs/cache/PLAN_LONG_HORIZON.md`
   - the current state summary and interpretation of what exists.
3. `docs/cache/ROADMAP_LONG_HORIZON.md`
   - the phased improvement roadmap.
4. `docs/LONG_HORIZON_OPERATOR_GUIDE.md`
   - practical guidance for safe, bounded operation.
5. `docs/cache/CHECKLIST_LONG_HORIZON.md`
   - validation and follow-up checklist.

## Document map

### Core definition and direction

- `docs/cache/SPEC_LONG_HORIZON.md`
  - defines the current behavioral contract,
  - describes required behavior, constraints, and acceptance examples.

- `docs/cache/PLAN_LONG_HORIZON.md`
  - describes the current architecture and strengths,
  - explains the current meaning of long-horizon support in Monitor,
  - summarizes improvement priorities.

- `docs/cache/ROADMAP_LONG_HORIZON.md`
  - breaks long-horizon work into phases,
  - identifies quick wins, medium-term architecture work, and higher-value
    future autonomy improvements.

### Operational guidance

- `docs/LONG_HORIZON_OPERATOR_GUIDE.md`
  - explains how to configure and use bounded orchestration safely,
  - provides practical guidance for operators.

- `docs/cache/CHECKLIST_LONG_HORIZON.md`
  - records validation items, implementation progress, and remaining gaps.

### Benchmark planning and execution

- `docs/BENCHMARK_USAGE.md`
  - concise primary guide for running, inspecting, and comparing repository
    benchmark runs,
  - useful before diving into the long-horizon cache docs.

- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
  - defines the Phase 2 benchmark plan,
  - lists scenarios, metrics, runtime profiles, and exit criteria.

- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
  - explains how to run benchmarks end to end,
  - provides execution discipline and evidence-capture guidance.

- `docs/cache/BENCHMARK_EXECUTION_QUEUE_LONG_HORIZON.md`
  - prioritizes which benchmark runs should execute next,
  - tracks readiness and execution status.

- `docs/cache/BENCHMARK_GAPS_LONG_HORIZON.md`
  - summarizes what is scaffolded versus what still lacks real evidence,
  - makes the transition from documentation to execution explicit.

- `docs/cache/BENCHMARK_RUN_TEMPLATE_LONG_HORIZON.md`
  - reusable template for recording a single benchmark run.

- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
  - top-level results index and summary scaffold,
  - used to aggregate executed benchmark evidence.

- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_1.md`
  - concrete prompt and fixture definition for the first real run,
  - makes `Scenario 1 / Profile A` ready for execution.

### Example benchmark run records

These are starter example records for scenario-specific benchmark execution.
They are examples, not executed benchmark evidence.

- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_3_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_4_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_5_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_7_PROFILE_C_EXAMPLE.md`

### Planned real-run benchmark records

These files are placeholders for upcoming executed benchmark runs.

- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md`

### Concrete fixture definitions for planned real runs

- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_1.md`
- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_2.md`
- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_3.md`
- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_4.md`
- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_5.md`
- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_6.md`
- `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_7.md`

## Which document should I use?

### I want to understand what "long-horizon" means here
Use:
- `docs/cache/SPEC_LONG_HORIZON.md`
- `docs/cache/PLAN_LONG_HORIZON.md`

### I want to know what we should do next
Use:
- `docs/cache/ROADMAP_LONG_HORIZON.md`
- `docs/cache/CHECKLIST_LONG_HORIZON.md`

### I want to operate Monitor safely for long tasks
Use:
- `docs/LONG_HORIZON_OPERATOR_GUIDE.md`

### I want to design or review benchmark work
Use:
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`

### I want to record or inspect benchmark runs
Use:
- `docs/cache/BENCHMARK_RUN_TEMPLATE_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- scenario-specific run records in `docs/cache/`

### I want to know whether evidence exists yet
Use:
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`

## Current state summary

At the moment, the long-horizon doc set includes:
- a behavior spec,
- a current-state plan document,
- a phased roadmap,
- an operator guide,
- a validation checklist,
- a benchmark plan,
- a benchmark execution playbook,
- a benchmark run template,
- example run records,
- planned real-run placeholders,
- a results index.

Benchmark planning and execution scaffolding exist.
Executed benchmark evidence is still expected to accumulate in
`docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`.

## Maintenance note

When adding new long-horizon docs, benchmark fixtures, or executed run records,
update this index so it remains the easiest navigation point for the overall
document set.
