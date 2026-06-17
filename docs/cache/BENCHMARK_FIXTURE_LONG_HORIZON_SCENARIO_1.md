# BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_1

Concrete prompt and fixture definition for the first real Phase 2 long-horizon
benchmark run.

This document is intended to make `Scenario 1 / Profile A` execution-ready by
specifying a benchmark shape, fixture requirements, prompt template,
verification expectations, scoring guidance, and evidence-capture discipline.

Primary linked run record:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md`

Related docs:
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- `docs/cache/INDEX_LONG_HORIZON.md`

## Scenario target

This fixture supports:
- **Scenario 1** — single-session multi-file feature
- **Profile A** — no orchestration

The goal is to measure whether Monitor can complete a realistic multi-file
feature workflow in one session with:
- explicit planning,
- a coherent read/edit/test loop,
- visible progress,
- disciplined verification,
- a final outcome summary that matches the actual work performed.

## Why this scenario should run first

This is the best first real benchmark because it:
- exercises the core long-horizon loop without delegation complexity,
- is easier to interpret than failure-path scenarios,
- provides a baseline for later delegated and resume benchmarks,
- tests whether planning and verification quality are already strong.

## Fixture requirements

Choose a repo task that satisfies all of the following:

1. **Moderate complexity**
   - not a trivial one-file rename,
   - not so large that success depends on hours of work.

2. **Multiple-file scope**
   - at least 2 source files should require inspection or modification,
   - at least 1 test file should be updated or added.

3. **Clear verification path**
   - the repo must have a targeted command that can validate the feature.

4. **Bounded ambiguity**
   - the task should require judgment,
   - but the expected outcome should still be understandable to a reviewer.

5. **No orchestration needed**
   - the feature should be appropriate for a single orchestrator session.

## Recommended task shape

Pick one moderate feature request with this structure:
- add or improve an existing capability,
- touch a small cluster of related files,
- update or extend tests,
- preserve existing architecture and conventions,
- finish in one session with targeted verification.

Good examples:
- extend an existing command or option with test coverage,
- add validation to a feature path and update its tests,
- improve output formatting behavior across multiple files,
- add a small but meaningful UX or tooling enhancement.

Avoid:
- pure documentation-only tasks,
- mass mechanical refactors,
- tasks with no meaningful tests,
- tasks that depend on unavailable external systems.

## Benchmark prompt template

Use a prompt in this shape and customize the bracketed fields.

```text
Implement a moderate multi-file feature in this repository.

Requirements:
- Update the existing [feature area / command / module] so that [desired behavior].
- Preserve existing architecture and repository conventions.
- Update or add tests that verify the new behavior.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Keep changes focused and production-ready.
- Finish in a single session without using sub-agent orchestration.

Please also summarize:
- which files changed,
- what verification was run,
- any remaining risks or follow-up work.
```

## Prompt customization checklist

Before running, replace placeholders with concrete details:
- [ ] feature area identified
- [ ] desired behavior stated clearly
- [ ] test surface identified
- [ ] targeted verification command known
- [ ] prompt reviewed for realism and bounded scope

## Example concrete prompt

Use this only as a pattern, not as a required repository-specific task.

```text
Implement a moderate multi-file feature in this repository.

Requirements:
- Update the existing CLI output path so that a user-facing summary includes a
  clearly labeled status section and a concise totals section.
- Preserve existing architecture and repository conventions.
- Update or add tests that verify the new behavior.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Keep changes focused and production-ready.
- Finish in a single session without using sub-agent orchestration.

Please also summarize:
- which files changed,
- what verification was run,
- any remaining risks or follow-up work.
```

## Runtime profile

Use **Profile A** exactly.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=0`
- `SUBAGENT_WRITE_ACCESS=none`

No sub-agents should be used for this run.

## Success criteria

A strong run should show all of the following:
- a visible todo plan for the non-trivial task,
- investigation before edits,
- edits spanning multiple related files,
- updated or added tests,
- targeted verification actually executed,
- a final summary consistent with the diff and verification output.

## Failure criteria

The run should be considered weak or failed if any of the following occur:
- no explicit plan is created,
- the task remains incomplete without a strong reason,
- edits are made without sufficient inspection,
- verification is skipped or only claimed without evidence,
- the final summary misstates completion or verification,
- the work collapses into repeated low-value tool loops.

## Measurement guidance

Record the following in the run file:
- whether a todo plan was created,
- number of files changed,
- whether tests were modified,
- total tool-call count,
- approximate peak tool-call depth,
- time to completion,
- verification command and outcome,
- qualitative scores for plan quality, progress visibility, failure honesty,
  and resume clarity.

For this scenario, delegation usefulness should be recorded as not applicable.

## Suggested verification discipline

Prefer targeted verification over broad suite execution when possible.

Good verification examples:
- a focused unit-test file,
- a narrow integration-test target,
- a project-specific command that exercises the changed feature path.

Avoid claiming verification based only on:
- static reasoning,
- successful file edits,
- partial command preparation without execution.

## Evidence to retain

Retain at minimum:
- exact initial prompt,
- completed run record,
- resulting diff,
- verification command and outcome,
- final summary provided at the end of the run.

If the run goes poorly, also retain:
- where it stalled,
- whether the todo plan was still useful,
- whether failure was surfaced honestly.

## Recommended scoring expectations

For a healthy first baseline run, a strong outcome would usually look like:
- Plan quality: `2`
- Progress visibility: `1` or `2`
- Failure honesty: `2`
- Resume clarity: `1` or `2`

These are not required target scores. They are only sanity-check expectations
for a successful baseline-quality run.

## Post-run update steps

After execution:
1. complete `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md`,
2. update `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`,
3. note any recurring bottlenecks,
4. identify whether the outcome changes roadmap priorities.

## Notes for reviewers

When reviewing the run, compare:
- the prompt,
- the todo plan quality,
- the actual diff,
- the verification evidence,
- the final summary.

The most important question is not only whether the run finished, but whether
it behaved like a trustworthy long-horizon coding workflow.
