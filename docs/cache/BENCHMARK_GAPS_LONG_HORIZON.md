# BENCHMARK_GAPS_LONG_HORIZON

Summary of what is already scaffolded for Phase 2 long-horizon benchmarking
versus what still lacks real execution evidence.

This document exists to make the current state explicit: the long-horizon
benchmark framework is now broadly documented, but benchmark execution evidence
still needs to be produced. It is intended to reduce ambiguity about whether
Phase 2 is blocked by planning work or by actual run execution.

Related docs:
- `docs/cache/INDEX_LONG_HORIZON.md`
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_EXECUTION_QUEUE_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`

## Purpose

Use this document to:
- distinguish scaffolding from evidence,
- identify the highest-priority missing benchmark outputs,
- avoid overclaiming Phase 2 maturity,
- make the next execution steps obvious.

## Current state summary

### What is complete in documentation form

The following benchmark-supporting artifacts now exist:
- benchmark plan,
- benchmark execution playbook,
- benchmark execution queue,
- benchmark results index,
- benchmark run template,
- example run records for Scenarios 1 through 7,
- planned real-run records for Scenarios 1 through 7,
- concrete fixture definitions for Scenarios 1 through 7,
- long-horizon documentation index.

In other words, the documentation framework for Phase 2 is substantially
complete.

### What is not yet complete in evidence form

The following still need real execution work:
- actual benchmark runs,
- completed run records with real observations,
- verification outputs tied to real runs,
- real delegated outcome data,
- measured tool-call and timing data,
- aggregated evidence in the results index,
- recurring bottleneck summaries based on observed runs,
- roadmap implications grounded in actual benchmark evidence.

In other words, the main remaining gap is **execution evidence**, not planning.

## Scaffolding versus evidence table

| Area | Documentation status | Evidence status | Notes |
| --- | --- | --- | --- |
| Benchmark scenarios | Complete | Not yet executed | All 7 scenarios are defined. |
| Runtime profiles | Complete | Not yet exercised systematically | Profiles A, B, and C are documented. |
| Run-record format | Complete | Not yet populated with real data | Template and placeholders exist. |
| Example benchmark runs | Complete | Not evidence | These are scaffolding only. |
| Planned real-run records | Complete | Not yet executed | All planned runs have placeholder files. |
| Fixture definitions | Complete | Not yet validated in practice | All scenarios now have concrete fixture docs. |
| Results index | Complete | Not yet populated with real results | Run IDs exist, but no executed rows yet. |
| Execution order | Complete | Not yet carried out | Queue is documented. |
| Failure-handling evidence | Partial | Missing | Framework exists, but no observed evidence yet. |
| Resume-behavior evidence | Partial | Missing | Scenario 5 fixture exists, but no real run yet. |
| Persistent-agent usefulness evidence | Partial | Missing | Scenario 6 fixture exists, but no real run yet. |
| Delegated-write boundary evidence | Partial | Missing | Scenario 7 fixture exists, but no real run yet. |

## Highest-priority missing evidence

The most important missing outputs are:

1. **A real baseline run for Scenario 1 / Profile A**
   - establishes the non-delegated baseline,
   - gives the first concrete completion, verification, and tool-use data.

2. **A real debugging run for Scenario 2 / Profile B**
   - validates investigate-before-edit behavior,
   - gives the first delegated-or-not debugging comparison point.

3. **A real interruption-and-resume run for Scenario 5 / Profile B**
   - gives the first direct evidence on session continuity and resume clarity,
   - informs Phase 3 priorities strongly.

4. **A real foreground-plus-audit run for Scenario 3 / Profile B**
   - validates whether bounded background delegation helps in practice.

5. **A real mixed delegated outcome run for Scenario 4 / Profile B**
   - validates whether failure states are surfaced honestly and usefully.

6. **A real persistent-agent follow-up run for Scenario 6 / Profile B**
   - validates whether persistent orchestration is genuinely helpful.

7. **A real delegated-write boundary run for Scenario 7 / Profile C**
   - validates whether delegated writes remain safe, bounded, and inspectable.

## What would count as real evidence

A benchmark run should count as real evidence only if it includes all of the
following:
- a completed non-example run record,
- a concrete prompt,
- actual observed execution details,
- verification command and outcome,
- preserved diff or repo-state evidence where applicable,
- results index updates reflecting the completed run.

The following do **not** count as real evidence by themselves:
- example run records,
- fixture definitions,
- queue entries,
- intended run IDs,
- theoretical expectations or scoring targets.

## Priority path to close the evidence gap

The recommended next sequence remains:
1. `LH-S1-A-001`
2. `LH-S2-B-001`
3. `LH-S5-B-001`
4. `LH-S3-B-001`
5. `LH-S4-B-001`
6. `LH-S6-B-001`
7. `LH-S7-C-001`

This order closes the most important uncertainty first:
- baseline execution quality,
- debugging quality,
- resume quality,
- bounded delegation quality,
- mixed-outcome trust,
- persistent-agent usefulness,
- delegated-write safety.

## Indicators that Phase 2 is truly underway

Phase 2 should be considered underway in an evidence-backed sense when:
- at least one real run is completed,
- the results index contains a real outcome row,
- a run record contains observed data rather than placeholders,
- real verification output is preserved,
- at least one qualitative finding is based on observation instead of design
  expectation.

## Indicators that Phase 2 is substantively complete

Phase 2 should be considered substantively complete when:
- core scenarios have at least one real executed run,
- the results index contains aggregated findings,
- recurring bottlenecks are documented from observed runs,
- roadmap implications are supported by benchmark evidence,
- planning no longer dominates the Phase 2 workstream.

## Practical takeaway

The benchmark design and documentation layer is now in strong shape.

The main risk is no longer lack of structure. The main risk is failing to turn
that structure into real benchmark evidence.

The immediate next move should therefore be execution of `LH-S1-A-001`, not
additional framework expansion unless a specific gap appears during execution.
