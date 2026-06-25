# BENCHMARK_RESULTS_LONG_HORIZON

Index and summary scaffold for Phase 2 long-horizon benchmark execution
results.

This document is the top-level place to track executed benchmark runs, summarize
outcomes across scenarios and runtime profiles, and record the most important
patterns discovered during validation. It pairs with:
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RUN_TEMPLATE_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
- the scenario-specific example run records in `docs/cache/`

## Purpose

Use this file to:
- index completed benchmark runs,
- summarize outcome trends,
- compare runtime profiles,
- capture recurring bottlenecks and failure modes,
- identify which roadmap priorities are now backed by benchmark evidence.

## Status

Current state:
- benchmark planning and execution scaffolding exist,
- Scenario 1 and Scenario 2 fixtures have been made repo-specific,
- the Scenario 1 nominated repo task has been implemented in code,
- the benchmark runner has been exercised successfully in-repo,
- no long-horizon Phase 2 run record has been completed yet.

Executed benchmark runs recorded here:
- no long-horizon run record has been completed yet.
- however, the general `monitor_bench` pipeline has now been exercised
  successfully as a repository benchmark workflow.

Planned first runs:
- `LH-S1-A-001` → `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md`
  - fixture: `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_1.md`
- `LH-S2-B-001` → `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md`
  - fixture: `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_2.md`
- `LH-S3-B-001` → `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_3_PROFILE_B.md`
  - fixture: `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_3.md`
- `LH-S4-B-001` → `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_4_PROFILE_B.md`
  - fixture: `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_4.md`
- `LH-S5-B-001` → `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_5_PROFILE_B.md`
  - fixture: `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_5.md`
- `LH-S6-B-001` → `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B.md`
  - fixture: `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_6.md`
- `LH-S7-C-001` → `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_7_PROFILE_C.md`
  - fixture: `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_7.md`

## How to use this document

1. Add a row to the run index for each executed benchmark.
2. Link the full run record.
3. Update the aggregate scenario and profile summaries.
4. Record notable failures, surprises, and follow-up actions.
5. Keep interpretation honest when evidence is thin or mixed.

## Run index

| Run ID | Scenario | Profile | Date | Result | Verification | Run record |
| --- | --- | --- | --- | --- | --- | --- |
| LH-S1-A-001 | Scenario 1 | Profile A | Planned | Not yet executed | Not yet executed | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md` |
| LH-S2-B-001 | Scenario 2 | Profile B | Planned | Not yet executed | Not yet executed | `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md` |

## Scenario summary

### Scenario 1 — single-session multi-file feature
- Runs completed:
- Completion rate:
- Verification pass rate:
- Notes:

### Scenario 2 — investigate-then-fix bug workflow
- Runs completed:
- Completion rate:
- Verification pass rate:
- Notes:

### Scenario 3 — background audit plus foreground implementation
- Runs completed:
- Completion rate:
- Verification pass rate:
- Notes:

### Scenario 4 — partial delegated failure
- Runs completed:
- Completion rate:
- Failure honesty observations:
- Notes:

### Scenario 5 — interruption and resume in the same session
- Runs completed:
- Recovery completion rate:
- Resume clarity observations:
- Notes:

### Scenario 6 — persistent-agent follow-up workflow
- Runs completed:
- Persistent follow-up success rate:
- Lifecycle observations:
- Notes:

### Scenario 7 — delegated-write boundary validation
- Runs completed:
- Denied-write enforcement rate:
- In-scope write success rate:
- Notes:

## Runtime profile summary

### Profile A — no orchestration
- Runs completed:
- Strengths:
- Weaknesses:
- Recommended uses:

### Profile B — bounded research delegation
- Runs completed:
- Strengths:
- Weaknesses:
- Recommended uses:

### Profile C — constrained delegated writing
- Runs completed:
- Strengths:
- Weaknesses:
- Recommended uses:

## Aggregate metrics

Track these metrics as benchmark evidence accumulates.

- Overall completion rate:
- Overall verification pass rate:
- Recovery completion rate after interruption:
- Delegated outcome mix: ok / failed / pending
- Typical tool-call count range:
- Typical peak tool-call depth range:
- Typical time-to-completion range:

## Qualitative findings

### Plan quality
- Observations:

### Progress visibility
- Observations:

### Failure honesty
- Observations:

### Resume clarity
- Observations:

### Delegation usefulness
- Observations:

## Recurring bottlenecks

Document repeating failure modes or operator pain points here.

- Responses chained user follow-ups can still hit `context_length_exceeded`
  even when visible input is tiny, because `previous_response_id` hides a large
  prior chain and the full tool catalog may still be resent.

## Follow-up actions

Use this section to connect benchmark evidence back to roadmap priorities.

- Recalibrate `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS["chained_user_followup"]`
  upward from the original `~2,000` seed toward a safer `~8,000` cap.
- Evaluate a conditional tool-inclusion policy for `chained_user_followup`
  using the future `UtilityLLM` helper so clearly non-tool-oriented turns can
  avoid paying the full tool-schema cost.

## Evidence-backed roadmap implications

Record which roadmap items now have real benchmark support behind them.

- _No evidence-backed implications recorded yet._

## Completion criteria for this results index

This document becomes substantively useful when:
- at least one real run is recorded for each core scenario class,
- Profiles A and B each have multiple executed runs,
- Profile C has at least one delegated-write boundary validation run,
- recurring failure modes are summarized,
- roadmap prioritization is updated based on observed results.
