# BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_5

Concrete prompt and fixture definition for an interruption-and-resume Phase 2
long-horizon benchmark run.

This document is intended to make `Scenario 5 / Profile B` execution-ready by
specifying a benchmark shape, fixture requirements, prompt template,
interruption procedure, verification expectations, scoring guidance, and
evidence-capture discipline.

Primary linked example run record:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_5_PROFILE_B_EXAMPLE.md`

Related docs:
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- `docs/cache/INDEX_LONG_HORIZON.md`

## Scenario target

This fixture supports:
- **Scenario 5** — interruption and resume in the same session
- **Profile B** — bounded research delegation

The goal is to measure whether Monitor can sustain a realistic multi-step task
across an intentional interruption with:
- explicit planning,
- meaningful partial progress before interruption,
- clear retained state,
- low-ambiguity resumption,
- disciplined verification after completion,
- an honest final summary that reflects both the interruption and recovery.

## Why this scenario matters early

This is one of the highest-value long-horizon behaviors to validate because it:
- tests whether session continuity is practically useful,
- exposes whether todo state alone is enough to resume effectively,
- reveals whether interruption causes confusion, duplication, or omission,
- provides direct evidence for Phase 3 resume and recovery priorities.

## Fixture requirements

Choose a repo task that satisfies all of the following:

1. **Multi-step but bounded work**
   - the task should be large enough that interruption is meaningful,
   - but still finishable in one session after resumption.

2. **Natural midpoint exists**
   - there should be an obvious point after investigation or partial edits where
     the run can pause without making the scenario artificial.

3. **Verification remains clear**
   - the repo should provide a targeted verification path once work is resumed
     and completed.

4. **Resume value is observable**
   - after interruption, it should matter whether the system retained plan state
     and current progress clearly.

5. **Delegation is optional but allowed**
   - a bounded read-only delegated task may be used,
   - but the main value of the scenario is resume clarity, not delegation count.

## Recommended task shape

Pick one task with this structure:
- inspect the relevant area,
- create a todo plan,
- begin implementation or investigation,
- reach a meaningful intermediate state,
- intentionally pause,
- resume later in the same session,
- complete remaining work,
- run targeted verification,
- summarize final result and any residual uncertainty.

Good examples:
- a moderate feature where implementation and tests happen in separate phases,
- a bugfix where diagnosis happens before the final repair,
- a task that naturally splits into investigation, modification, and
  verification.

Avoid:
- trivial tasks that finish before interruption matters,
- tasks with no obvious midpoint,
- tasks whose verification depends on unstable external systems,
- tasks so large that failure to finish is unsurprising.

## Benchmark prompt template

Use a prompt in this shape and customize the bracketed fields.

```text
Complete a moderate multi-step coding task in this repository, but do it in a
way that allows an intentional pause and later resumption in the same session.

Requirements:
- Work in the [feature area / command / module / test surface] so that
  [desired behavior or bugfix goal].
- Preserve existing architecture and repository conventions.
- Update or add tests if needed.
- Run targeted verification before final completion.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Reach a meaningful intermediate state before the intentional interruption.
- After interruption, resume using retained session state instead of starting
  over.
- Use bounded sub-agent delegation only if it materially helps.
- Keep changes focused and production-ready.

Please also summarize:
- what was complete before interruption,
- what remained to do after interruption,
- what verification was run,
- any remaining risks or follow-up work.
```

## Prompt customization checklist

Before running, replace placeholders with concrete details:
- [ ] task area identified
- [ ] desired behavior or fix goal stated clearly
- [ ] natural interruption point identified
- [ ] targeted verification command known
- [ ] resume success criteria identified
- [ ] delegation opportunity identified if applicable
- [ ] prompt reviewed for realism and bounded scope

## Example concrete prompt

Use this only as a pattern, not as a required repository-specific task.

```text
Complete a moderate multi-step coding task in this repository, but do it in a
way that allows an intentional pause and later resumption in the same session.

Requirements:
- Work in an existing output or validation path so that a moderate behavior
  improvement or bugfix can be implemented across a few related files.
- Preserve existing architecture and repository conventions.
- Update or add tests if needed.
- Run targeted verification before final completion.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Reach a meaningful intermediate state before the intentional interruption.
- After interruption, resume using retained session state instead of starting
  over.
- Use bounded sub-agent delegation only if it materially helps.
- Keep changes focused and production-ready.

Please also summarize:
- what was complete before interruption,
- what remained to do after interruption,
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

Sub-agent use is allowed but should remain bounded and clearly secondary to the
resume behavior being tested.

## Interruption procedure

The interruption should be intentional and documented.

### Recommended interruption timing

Pause only after at least one meaningful milestone has occurred, such as:
- the todo plan exists,
- relevant files have been inspected,
- partial edits have been made,
- some but not all planned work is complete.

Do not interrupt so early that resume is trivial.
Do not interrupt so late that almost no meaningful work remains.

### What to record at interruption time

At the interruption point, record:
- which todo items are done,
- which todo item is in progress,
- which files have already changed,
- whether any verification has already run,
- whether any delegated work is still pending,
- what work clearly remains.

### Resume prompt guidance

When resuming, prefer a short prompt that asks the session to continue based on
retained state.

Example:

```text
Resume the interrupted task from the current session state. Continue from the
existing plan, avoid repeating completed work, finish the remaining steps, run
verification, and summarize the final result.
```

The point is to test whether retained plan and session state are actually
useful.

## Success criteria

A strong run should show all of the following:
- a visible todo plan before interruption,
- meaningful progress before pausing,
- retained state that makes resumption straightforward,
- little or no unnecessary repetition after resumption,
- completion with targeted verification,
- a final summary consistent with both the interruption state and final outcome.

If delegation is used, a strong run should also show:
- delegation remained bounded,
- delegated work did not obscure the main resume path,
- delegated findings remained understandable after resumption.

## Failure criteria

The run should be considered weak or failed if any of the following occur:
- the interruption happens before meaningful state exists,
- resumption requires heavy transcript archaeology,
- completed work is unnecessarily repeated,
- important unfinished work is forgotten,
- verification is skipped or only claimed without evidence,
- final reporting is unclear about what happened before and after interruption.

## Measurement guidance

Record the following in the run file:
- whether a todo plan was created,
- what state existed at interruption time,
- tool-call count before interruption,
- tool-call count after resumption,
- approximate peak tool-call depth,
- whether delegation was used,
- delegated outcome mix if applicable,
- time to interruption,
- time from resumption to completion,
- total time to completion,
- verification command and outcome,
- qualitative scores for plan quality, progress visibility, failure honesty,
  resume clarity, and delegation usefulness.

## Suggested verification discipline

Verification should occur after resumed completion and should reflect the final
state of the task.

Good verification examples:
- focused unit-test execution,
- narrow integration verification,
- a project-specific command that exercises the final changed path.

Avoid claiming success based only on:
- partial progress before interruption,
- a plausible resume narrative,
- successful edits without execution of verification.

## Evidence to retain

Retain at minimum:
- exact initial prompt,
- interruption-point notes,
- resume prompt,
- completed run record,
- resulting diff,
- verification command and outcome,
- final summary provided at the end of the run.

If delegation is used, also retain:
- delegated task summary,
- whether delegated work completed before or after interruption,
- any pending or failed delegated state details.

If the run goes poorly, also retain:
- what caused resume confusion,
- whether the todo plan still helped,
- whether uncertainty or partial completion was surfaced honestly.

## Recommended scoring expectations

For a healthy early interruption benchmark, a strong outcome would usually look
like:
- Plan quality: `2`
- Progress visibility: `1` or `2`
- Failure honesty: `2`
- Resume clarity: `2`
- Delegation usefulness: `1` or `2` if delegation is used

These are not required target scores. They are only sanity-check expectations
for a successful early benchmark-quality run.

## Post-run update steps

After execution:
1. create or complete a non-example run record for Scenario 5,
2. update `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`,
3. record whether resume was straightforward or fragile,
4. note any repeated rework or dropped state,
5. identify whether the outcome changes Phase 3 priority or scope.

## Notes for reviewers

When reviewing the run, compare:
- the initial prompt,
- the interruption-point record,
- the resume prompt,
- the final diff,
- the verification evidence,
- the final summary.

The most important question is whether Monitor behaved like a trustworthy
long-horizon assistant across interruption, not merely whether the final code
ended in a good state.
