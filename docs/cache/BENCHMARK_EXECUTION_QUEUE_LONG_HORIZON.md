# BENCHMARK_EXECUTION_QUEUE_LONG_HORIZON

Execution queue for Phase 2 long-horizon benchmark runs.

This document is the bridge between benchmark scaffolding and real benchmark
execution. It prioritizes which runs should happen first, records readiness,
and makes it easy to see what is prepared versus what still needs execution.

Related docs:
- `docs/cache/INDEX_LONG_HORIZON.md`
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_GAPS_LONG_HORIZON.md`

## Purpose

Use this queue to:
- identify the next benchmark run to execute,
- track whether each run has fixture and record scaffolding,
- separate planned work from executed evidence,
- prioritize runs that produce the most useful early signal.

## Queue status meanings

- **Ready**
  - fixture exists,
  - planned real-run record exists,
  - runtime profile is known,
  - no additional doc scaffolding is needed before execution.

- **Needs fixture**
  - a run is planned, but concrete execution guidance is missing.

- **Needs run record**
  - a fixture exists, but no planned real-run record exists.

- **In progress**
  - execution has started, but the final run record is not complete.

- **Executed**
  - a real run has completed and is reflected in the results index.

- **Blocked**
  - execution is currently blocked by missing repo fixture, environment, or
    other practical constraints.

## Recommended execution order

This order reflects the current recommendation for highest-value early signal.

1. `LH-S1-A-001` — Scenario 1 / Profile A
2. `LH-S2-B-001` — Scenario 2 / Profile B
3. `LH-S5-B-001` — Scenario 5 / Profile B
4. `LH-S3-B-001` — Scenario 3 / Profile B
5. `LH-S4-B-001` — Scenario 4 / Profile B
6. `LH-S6-B-001` — Scenario 6 / Profile B
7. `LH-S7-C-001` — Scenario 7 / Profile C

## Execution queue

| Priority | Run ID | Scenario | Profile | Fixture | Run record | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `LH-S1-A-001` | Scenario 1 | Profile A | `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_1.md` | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md` | Ready | Best baseline run. |
| 2 | `LH-S2-B-001` | Scenario 2 | Profile B | `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_2.md` | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md` | Ready | Best early debugging benchmark. |
| 3 | `LH-S5-B-001` | Scenario 5 | Profile B | `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_5.md` | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_5_PROFILE_B.md` | Ready | High-value interruption/resume validation. |
| 4 | `LH-S3-B-001` | Scenario 3 | Profile B | `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_3.md` | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_3_PROFILE_B.md` | Ready | Foreground plus bounded audit. |
| 5 | `LH-S4-B-001` | Scenario 4 | Profile B | `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_4.md` | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_4_PROFILE_B.md` | Ready | Mixed delegated outcome trust test. |
| 6 | `LH-S6-B-001` | Scenario 6 | Profile B | `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_6.md` | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B.md` | Ready | Persistent-agent usefulness test. |
| 7 | `LH-S7-C-001` | Scenario 7 | Profile C | `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_7.md` | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_7_PROFILE_C.md` | Ready | Delegated-write boundary validation. |

## Immediate next run

The current recommended next run is:
- `LH-S1-A-001`

Why:
- it gives the clearest baseline,
- it avoids delegation complexity,
- it establishes a comparison point for later Profile B and Profile C runs.

## After each execution

When a run is executed:
1. update its status in this queue,
2. complete the corresponding run record,
3. update `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`,
4. note any blockers or environment issues that affect later runs,
5. adjust queue priority if new evidence changes what should run next.

## Blocking checklist for real execution

Before starting any queued run, confirm:
- [ ] the repository fixture is selected,
- [ ] the runtime profile is configured,
- [ ] the run record file is ready,
- [ ] verification commands are known,
- [ ] evidence capture location is chosen,
- [ ] operator time is sufficient for the scenario.

## Reprioritization guidance

You may reorder the queue if:
- a required fixture is not currently practical,
- a higher-priority run is blocked by environment or repo state,
- new product questions make a later scenario more urgent,
- benchmark evidence suggests a specific risk area needs earlier validation.

When reprioritizing, preserve a note explaining why the order changed.

## Current assessment

All currently planned benchmark runs are documentation-ready.
In addition:
- Scenario 1 and Scenario 2 now have repo-specific fixture guidance,
- the Scenario 1 nominated repo task has already been implemented in code,
- the general `monitor_bench` workflow has been exercised successfully in-repo,
- a concise primary benchmark usage guide now exists at
  `docs/BENCHMARK_USAGE.md`.

The main remaining work is still long-horizon execution and evidence capture,
not additional framework design.
