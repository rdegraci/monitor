# BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_3

Concrete prompt and fixture definition for a background-audit plus
foreground-implementation Phase 2 long-horizon benchmark run.

This document is intended to make `Scenario 3 / Profile B` execution-ready by
specifying a benchmark shape, fixture requirements, prompt template,
delegation guidance, verification expectations, scoring guidance, and
evidence-capture discipline.

Primary linked example run record:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_3_PROFILE_B_EXAMPLE.md`

Related docs:
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- `docs/cache/INDEX_LONG_HORIZON.md`

## Scenario target

This fixture supports:
- **Scenario 3** — background audit plus foreground implementation
- **Profile B** — bounded research delegation

The goal is to measure whether Monitor can execute a realistic two-track coding
workflow with:
- explicit planning,
- useful decomposition between foreground work and delegated background audit,
- continued mainline progress while delegation is active,
- clear synthesis of delegated findings,
- disciplined verification,
- an honest final summary of both the implementation and audit outcomes.

## Why this scenario matters early

This is one of the most important delegation benchmarks because it:
- tests whether orchestration helps rather than hinders core coding work,
- reveals whether delegated work can stay independent and genuinely useful,
- exposes visibility and synthesis quality under concurrent activity,
- provides evidence for Phase 5 artifact flow and Phase 7 observability work.

## Fixture requirements

Choose a repo task that satisfies all of the following:

1. **A meaningful main implementation task exists**
   - the foreground task should involve a moderate feature or focused bugfix,
   - it should require edits and verification in the main session.

2. **An independent audit branch exists**
   - there should be related call sites, adjacent files, or downstream surfaces
     that can be inspected independently of the main code changes.

3. **Foreground and background work can proceed in parallel**
   - the delegated audit should not need to make mainline decisions in real
     time,
   - the main session should be able to continue without blocking.

4. **Verification remains concrete**
   - the foreground task should have a clear targeted verification path,
   - any follow-up changes informed by the audit should also be reviewable.

5. **Delegation is worthwhile but bounded**
   - the audit should be useful enough to justify delegation,
   - but not broad enough to become an uncontrolled research project.

## Recommended task shape

Pick one task with this structure:
- inspect the main implementation area,
- create a todo plan,
- begin the main implementation,
- spawn one bounded read-only background audit,
- continue foreground work without waiting,
- receive or gather delegated findings,
- apply any necessary follow-up changes,
- run targeted verification,
- summarize final outcomes and residual risks.

Good examples:
- implement a targeted behavior change while auditing similar logic elsewhere,
- fix a focused bug while delegating a search for adjacent regressions,
- improve a command or output path while auditing related formatting or
  classification surfaces.

Avoid:
- tasks where the delegated branch is tightly coupled to every foreground step,
- tasks with no meaningful adjacent audit opportunity,
- tasks requiring multiple layers of recursive delegation,
- tasks whose verification depends on unstable external systems.

## Benchmark prompt template

Use a prompt in this shape and customize the bracketed fields.

```text
Implement a moderate change in this repository while also auditing adjacent
surfaces in the background for related risks or consistency issues.

Requirements:
- Update the [feature area / command / module / output path] so that
  [desired behavior or bugfix goal].
- Preserve existing architecture and repository conventions.
- Use bounded background delegation for an independent audit of related files,
  call sites, or adjacent behavior if that helps.
- Update or add tests if needed.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Keep foreground implementation moving while delegated work runs.
- Use sub-agents only for independent background investigation.
- Synthesize delegated findings clearly before final completion.
- Keep changes focused and production-ready.

Please also summarize:
- what the foreground implementation changed,
- what the background audit found,
- what verification was run,
- any remaining risks or follow-up work.
```

## Prompt customization checklist

Before running, replace placeholders with concrete details:
- [ ] main task area identified
- [ ] desired behavior or fix goal stated clearly
- [ ] independent audit target identified
- [ ] targeted verification command known
- [ ] delegated audit scope bounded clearly
- [ ] prompt reviewed for realism and bounded scope

## Example concrete prompt

Use this only as a pattern, not as a required repository-specific task.

```text
Implement a moderate change in this repository while also auditing adjacent
surfaces in the background for related risks or consistency issues.

Requirements:
- Update an existing output, validation, or result-processing path so that a
  focused behavior improvement or bugfix is implemented across a few related
  files.
- Preserve existing architecture and repository conventions.
- Use bounded background delegation for an independent audit of related files,
  call sites, or adjacent behavior if that helps.
- Update or add tests if needed.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Keep foreground implementation moving while delegated work runs.
- Use sub-agents only for independent background investigation.
- Synthesize delegated findings clearly before final completion.
- Keep changes focused and production-ready.

Please also summarize:
- what the foreground implementation changed,
- what the background audit found,
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

Delegation should remain bounded and read-only.

## Delegation guidance

This scenario is intended to use delegation deliberately.

### Good delegated audit tasks

Examples of appropriate delegated tasks:
- search for similar logic in adjacent files,
- audit call sites that consume the changed behavior,
- inspect tests or helper paths for consistency issues,
- identify nearby regressions or edge cases that the foreground task may miss.

### Poor delegated audit tasks

Avoid delegating:
- the main implementation itself,
- tasks that require constant back-and-forth with foreground code edits,
- ambiguous user-intent decisions,
- trivial inspection that the main session could do faster inline.

### What a good outcome looks like

A strong delegated audit result should be:
- concise,
- actionable,
- clearly scoped,
- easy to synthesize into the main session.

## Success criteria

A strong run should show all of the following:
- a visible todo plan,
- a meaningful foreground implementation path,
- one or more bounded delegated audits that remain independent,
- continued foreground progress while delegated work is active,
- clear incorporation or rejection of delegated findings,
- targeted verification actually executed,
- an honest final summary that distinguishes implementation outcome from audit
  outcome.

## Failure criteria

The run should be considered weak or failed if any of the following occur:
- foreground progress stalls waiting on delegation unnecessarily,
- delegated work is too vague, too broad, or too coupled to the main edits,
- delegated results are noisy or unusable,
- verification is skipped or only claimed without evidence,
- the final summary obscures what came from the main task versus the audit,
- the workflow collapses into confusing parallel activity with weak synthesis.

## Measurement guidance

Record the following in the run file:
- whether a todo plan was created,
- whether delegation was used,
- how many sub-agents were spawned,
- whether foreground work continued while delegation was active,
- delegated outcome mix,
- whether delegated results materially helped,
- number of files changed,
- whether tests were modified,
- total tool-call count,
- approximate peak tool-call depth,
- time to completion,
- verification command and outcome,
- qualitative scores for plan quality, progress visibility, failure honesty,
  resume clarity, and delegation usefulness.

## Suggested verification discipline

Verification should cover the foreground implementation and any follow-up changes
motivated by delegated findings.

Good verification examples:
- focused unit-test execution,
- narrow integration verification,
- project-specific commands that exercise the changed behavior.

Avoid claiming success based only on:
- a plausible implementation,
- a delegated audit summary,
- successful edits without execution of verification.

## Evidence to retain

Retain at minimum:
- exact initial prompt,
- delegated task prompt or summary,
- completed run record,
- resulting diff,
- verification command and outcome,
- final summary provided at the end of the run.

Also retain:
- whether foreground progress continued during delegated activity,
- whether delegated findings were acted on,
- whether any delegated work failed or remained pending.

If the run goes poorly, also retain:
- where the foreground path stalled,
- whether delegated work added more overhead than value,
- whether concurrent progress remained understandable to an operator.

## Recommended scoring expectations

For a healthy early foreground-plus-audit benchmark, a strong outcome would
usually look like:
- Plan quality: `2`
- Progress visibility: `1` or `2`
- Failure honesty: `2`
- Resume clarity: `1`
- Delegation usefulness: `2`

These are not required target scores. They are only sanity-check expectations
for a successful early benchmark-quality run.

## Post-run update steps

After execution:
1. create or complete a non-example run record for Scenario 3,
2. update `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`,
3. record whether delegation accelerated, distracted, or was neutral,
4. note any recurring synthesis or visibility weaknesses,
5. identify whether the outcome changes Phase 5 or Phase 7 priority or scope.

## Notes for reviewers

When reviewing the run, compare:
- the initial prompt,
- the foreground task progress,
- the delegated task scope and result,
- the final diff,
- the verification evidence,
- the final summary.

The most important question is whether Monitor behaved like a trustworthy
foreground orchestrator that used bounded background delegation effectively.
