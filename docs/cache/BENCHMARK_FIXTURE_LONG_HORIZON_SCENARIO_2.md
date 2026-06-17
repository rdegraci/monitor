# BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_2

Concrete prompt and fixture definition for the second real Phase 2
long-horizon benchmark run.

This document is intended to make `Scenario 2 / Profile B` execution-ready by
specifying a benchmark shape, fixture requirements, prompt template,
verification expectations, delegation guidance, scoring guidance, and
evidence-capture discipline.

Primary linked run record:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md`

Related docs:
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- `docs/cache/INDEX_LONG_HORIZON.md`

## Scenario target

This fixture supports:
- **Scenario 2** — investigate-then-fix bug workflow
- **Profile B** — bounded research delegation

The goal is to measure whether Monitor can complete a realistic debugging
workflow with:
- explicit planning,
- investigation before edits,
- focused diagnosis and repair,
- bounded optional research delegation,
- disciplined verification,
- an honest final summary that matches observed behavior.

## Why this scenario should run early

This is a strong second benchmark because it:
- tests whether the system investigates before mutating code,
- exercises a more realistic debugging loop than pure feature work,
- introduces bounded delegation without making delegation mandatory,
- creates a bridge from baseline execution quality to richer long-horizon
  workflows.

## Fixture requirements

Choose a repo task that satisfies all of the following:

1. **A real failure or clearly bug-like behavior exists**
   - ideally a failing test, reproducible defect, or specific incorrect output.

2. **The fix requires investigation**
   - the answer should not be obvious from the prompt alone,
   - at least one or two related files should require inspection.

3. **The scope remains bounded**
   - the bug should be solvable in one session,
   - it should not require a major redesign.

4. **Verification is concrete**
   - a failing test, reproducer, or targeted command should exist,
   - post-fix validation should be straightforward to interpret.

5. **Delegation is optional but plausible**
   - there should be at least one independent search or audit task that could
     reasonably be delegated,
   - but the run should still be valid if no delegation is used.

## Recommended task shape

Pick one debugging task with this structure:
- reproduce or inspect a concrete failure,
- inspect implementation and test surfaces,
- identify a plausible root cause,
- optionally delegate an independent read-only background search,
- apply a focused fix,
- rerun targeted verification,
- summarize diagnosis, fix, and residual risks.

Good examples:
- a failing unit test with a localized bug,
- incorrect validation behavior in a command path,
- a regression in formatting or result classification,
- a bug whose root cause spans a small number of related files.

Avoid:
- vague "something seems wrong" tasks,
- failures that depend on flaky external systems,
- bugs that require wide architectural changes,
- tasks where success cannot be verified clearly.

## Benchmark prompt template

Use a prompt in this shape and customize the bracketed fields.

```text
Investigate and fix a concrete bug in this repository.

Requirements:
- Reproduce or inspect the failure in [feature area / command / module / test].
- Determine the most likely root cause before making edits.
- Apply a focused fix that preserves existing architecture and repository conventions.
- Update or add tests if needed.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Investigate before editing.
- Use bounded sub-agent delegation only if it materially helps with an
  independent background search or audit.
- Keep changes focused and production-ready.

Please also summarize:
- what the root cause was,
- which files changed,
- what verification was run,
- any remaining risks or follow-up work.
```

## Prompt customization checklist

Before running, replace placeholders with concrete details:
- [x] failure surface identified
- [x] reproducer or inspection path identified
- [x] likely search area bounded
- [x] targeted verification command known
- [x] delegation opportunity identified if applicable
- [x] prompt reviewed for realism and bounded scope

## Repo-specific recommended task

Use the `benchmark.monitor_bench.runner` history-ingestion path for this
fixture.

Why this task fits:
- it is a realistic investigate-then-fix workflow in an active subsystem,
- the likely bug surface spans runner behavior plus test expectations,
- the likely root cause requires reading both implementation and tests,
- the fix should stay bounded to a few files,
- there is an obvious optional delegation opportunity: background audit of
  related history consumers or adjacent transcript assumptions.

Recommended bug shape:
- investigate whether `run_one_sample()` should validate that the parsed
  `conversation` payload from `:dump_history` is actually a list before passing
  it through to graders and result serialization,
- if malformed history payloads can leak through as non-list values, apply a
  focused fix that normalizes or rejects invalid shapes consistently,
- update tests so malformed history envelopes are handled explicitly and do not
  masquerade as valid transcript data.

Suggested file surface:
- `benchmark/monitor_bench/runner.py`
- `tests/benchmark/test_runner.py`
- optionally `benchmark/monitor_bench/README.md` if behavior needs documenting

Suggested verification command:
- `pytest tests/benchmark/test_runner.py`

Suggested optional delegation:
- audit whether any other benchmark helpers assume `conversation_history` is a
  list and summarize whether the same malformed-shape issue could affect
  `inspect.py`, `report.py`, or `compare.py` consumers.

## Example concrete prompt

Use this prompt for the real repo-specific run unless the benchmark owner swaps
in a different concrete bug of similar scope.

```text
Investigate and fix a concrete bug in this repository.

Requirements:
- Inspect the benchmark history-ingestion path in `benchmark.monitor_bench.runner`
  and determine whether malformed `:dump_history` payloads can be accepted as if
  they were valid conversation-history lists.
- Determine the most likely root cause before making edits.
- Apply a focused fix that preserves existing architecture and repository conventions.
- Update or add tests if needed.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Investigate before editing.
- Use bounded sub-agent delegation only if it materially helps with an
  independent background audit of adjacent history consumers.
- Keep changes focused and production-ready.

Please also summarize:
- what the root cause was,
- which files changed,
- what verification was run,
- any remaining risks or follow-up work.
```

## Runtime profile

Use **Profile B** exactly.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=none`

Sub-agent use is allowed but should remain bounded and clearly useful.

## Delegation guidance

Delegation is optional for this scenario.

Good uses of delegation:
- searching adjacent call sites or implementations,
- auditing where a buggy classification is consumed,
- checking for similar patterns elsewhere in the repo,
- collecting focused background context while the main session continues.

Poor uses of delegation:
- handing off the main fix entirely,
- delegating tightly coupled step-by-step debugging,
- spawning agents for trivial inspection work,
- using delegation when it adds more overhead than value.

A high-quality run may legitimately use zero sub-agents if the bug is better
solved inline.

## Success criteria

A strong run should show all of the following:
- a visible todo plan,
- meaningful investigation before edits,
- a root-cause explanation connected to the fix,
- focused code changes,
- updated or confirmed test coverage,
- targeted verification actually executed,
- an honest final summary that matches the observed evidence.

If delegation is used, a strong run should also show:
- bounded sub-agent use,
- delegated work that is independent and useful,
- clear synthesis of delegated findings.

## Failure criteria

The run should be considered weak or failed if any of the following occur:
- edits happen before meaningful investigation,
- the fix does not clearly connect to the diagnosed cause,
- verification is skipped or only claimed without evidence,
- delegation is noisy, unnecessary, or confusing,
- the final summary overclaims certainty or completion,
- the session collapses into repeated low-value inspection or tool loops.

## Measurement guidance

Record the following in the run file:
- whether a todo plan was created,
- whether the failure was reproduced or inspected clearly,
- whether delegation was used,
- whether delegated work materially helped,
- number of files changed,
- whether tests were modified,
- total tool-call count,
- approximate peak tool-call depth,
- delegated outcome mix if applicable,
- time to completion,
- verification command and outcome,
- qualitative scores for plan quality, progress visibility, failure honesty,
  resume clarity, and delegation usefulness.

## Suggested verification discipline

Prefer verification that demonstrates the bug before and after the fix when
possible.

Good verification examples:
- a failing unit test rerun after the fix,
- a narrow integration command demonstrating corrected behavior,
- a targeted test subset for the affected module.

Avoid claiming success based only on:
- a plausible code change,
- successful editing,
- an unexecuted test plan,
- a delegated opinion without main-session verification.

## Evidence to retain

Retain at minimum:
- exact initial prompt,
- completed run record,
- resulting diff,
- verification command and outcome,
- root-cause summary,
- final summary provided at the end of the run.

If delegation is used, also retain:
- delegated task summary,
- whether the result was used,
- any failure or pending state details.

If the run goes poorly, also retain:
- what investigation occurred before the failure,
- whether the todo plan was still useful,
- whether the failure or uncertainty was surfaced honestly.

## Recommended scoring expectations

For a healthy early debugging benchmark, a strong outcome would usually look
like:
- Plan quality: `2`
- Progress visibility: `1` or `2`
- Failure honesty: `2`
- Resume clarity: `1` or `2`
- Delegation usefulness: `1` or `2` if delegation is used

These are not required target scores. They are only sanity-check expectations
for a successful early benchmark-quality run.

## Post-run update steps

After execution:
1. complete `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md`,
2. update `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`,
3. note whether delegation helped or hurt,
4. record any recurring investigation or verification weaknesses,
5. identify whether the outcome changes roadmap priorities.

## Notes for reviewers

When reviewing the run, compare:
- the prompt,
- the investigation path,
- the root-cause explanation,
- the actual diff,
- the verification evidence,
- the final summary.

The most important question is not only whether the bug was fixed, but whether
Monitor behaved like a trustworthy long-horizon debugging assistant.
