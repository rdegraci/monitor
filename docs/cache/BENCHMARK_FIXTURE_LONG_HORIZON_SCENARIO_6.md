# BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_6

Concrete prompt and fixture definition for a persistent-agent follow-up Phase 2
long-horizon benchmark run.

This document is intended to make `Scenario 6 / Profile B` execution-ready by
specifying a benchmark shape, fixture requirements, prompt template,
persistent-agent lifecycle guidance, verification expectations, scoring
guidance, and evidence-capture discipline.

Primary linked example run record:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B_EXAMPLE.md`

Related docs:
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- `docs/cache/INDEX_LONG_HORIZON.md`

## Scenario target

This fixture supports:
- **Scenario 6** — persistent-agent follow-up workflow
- **Profile B** — bounded research delegation

The goal is to measure whether Monitor can use a persistent sub-agent
productively over multiple interactions, with:
- explicit planning,
- a bounded delegated side investigation,
- one or more useful follow-up prompts,
- clear lifecycle visibility and control,
- disciplined verification for any main-session changes,
- an honest final summary of both the main task and the persistent-agent work.

## Why this scenario matters

This is the most important persistent-agent benchmark because it:
- tests whether persistent agents are practically useful rather than merely
  available,
- reveals whether follow-up prompts improve delegated results,
- exposes lifecycle and cleanup clarity,
- provides direct evidence for persistent-agent workflow hardening priorities.

## Fixture requirements

Choose a repo task that satisfies all of the following:

1. **A meaningful mainline task exists**
   - the main session should have useful work to continue while the persistent
     sub-agent remains available,
   - the benchmark should not reduce to only interacting with the sub-agent.

2. **A bounded side investigation exists**
   - there should be a research or audit branch that is useful but not urgent,
   - the delegated task should benefit from at least one follow-up refinement.

3. **Follow-up prompts are plausible**
   - the delegated task should naturally support narrowing, extending, or
     clarifying the investigation after the first result.

4. **Lifecycle visibility matters**
   - it should be observable whether the agent stays available, responds to
     follow-up, and is eventually gathered or terminated cleanly.

5. **Verification remains concrete**
   - if the main session changes code, the repo should provide a clear targeted
     verification path.

## Recommended task shape

Pick one task with this structure:
- inspect the main task area,
- create a todo plan,
- start a persistent read-only research agent,
- continue mainline work while the agent remains available,
- send at least one follow-up prompt that narrows or extends the delegated
  investigation,
- gather, inspect, or synthesize the delegated findings,
- terminate the persistent agent cleanly if still active,
- run targeted verification if main-session code changed,
- summarize mainline and delegated outcomes honestly.

Good examples:
- implement or inspect a focused code path while a persistent agent audits edge
  cases or adjacent call sites,
- fix a bounded bug while a persistent agent checks for related regressions or
  similar patterns,
- evaluate a local change while a persistent agent performs a multi-step,
  follow-up-driven side investigation.

Avoid:
- tasks where the persistent agent is unnecessary compared with one-shot work,
- tasks requiring recursive delegation,
- tasks with no meaningful follow-up opportunity,
- tasks whose success depends on broad, uncontrolled agent behavior.

## Benchmark prompt template

Use a prompt in this shape and customize the bracketed fields.

```text
Complete a moderate coding task in this repository while also using a
persistent research sub-agent for a bounded side investigation that will need
at least one follow-up prompt.

Requirements:
- Work in the [feature area / command / module / output path] so that
  [desired behavior or bugfix goal].
- Preserve existing architecture and repository conventions.
- Use a persistent read-only sub-agent for an independent side investigation
  that may need narrowing or clarification after the first result.
- Continue useful main-session work while the persistent agent remains
  available.
- Update or add tests if needed.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Use the persistent agent only for independent background investigation.
- Send at least one follow-up prompt to improve or refine the delegated result.
- Clean up persistent-agent lifecycle clearly.
- Keep changes focused and production-ready.

Please also summarize:
- what the mainline task changed,
- what the persistent agent initially reported,
- what the follow-up clarified or added,
- what verification was run,
- any remaining risks or follow-up work.
```

## Prompt customization checklist

Before running, replace placeholders with concrete details:
- [ ] main task area identified
- [ ] desired behavior or fix goal stated clearly
- [ ] side investigation target identified
- [ ] follow-up refinement opportunity identified
- [ ] targeted verification command known
- [ ] prompt reviewed for realism and bounded scope

## Example concrete prompt

Use this only as a pattern, not as a required repository-specific task.

```text
Complete a moderate coding task in this repository while also using a
persistent research sub-agent for a bounded side investigation that will need
at least one follow-up prompt.

Requirements:
- Work in an existing output, validation, or result-processing path so that a
  focused behavior improvement or bugfix is implemented across a few related
  files.
- Preserve existing architecture and repository conventions.
- Use a persistent read-only sub-agent for an independent side investigation
  that may need narrowing or clarification after the first result.
- Continue useful main-session work while the persistent agent remains
  available.
- Update or add tests if needed.
- Run targeted verification and summarize the outcome.

Expectations:
- Create and maintain an explicit todo plan.
- Inspect existing code before editing.
- Use the persistent agent only for independent background investigation.
- Send at least one follow-up prompt to improve or refine the delegated result.
- Clean up persistent-agent lifecycle clearly.
- Keep changes focused and production-ready.

Please also summarize:
- what the mainline task changed,
- what the persistent agent initially reported,
- what the follow-up clarified or added,
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

Persistent agents should remain read-only and bounded.

## Persistent-agent lifecycle guidance

This scenario is only useful if persistence actually matters.

### Required lifecycle elements

The run should include:
- creation of a persistent sub-agent,
- at least one follow-up prompt,
- observation of whether the agent stays available,
- clear final handling by gather, inspection, idle reap observation, or explicit
  kill as appropriate.

### Good follow-up prompts

Useful follow-up prompts usually:
- narrow scope based on the first result,
- ask for targeted confirmation of one finding,
- extend the search to one adjacent surface,
- request a more concise or structured summary.

### Poor follow-up prompts

Avoid follow-up prompts that:
- restate the original task without refinement,
- ask the persistent agent to take over the mainline task,
- introduce broad new unrelated work,
- require constant back-and-forth for tightly coupled coding decisions.

### What a good outcome looks like

A strong persistent-agent run should show:
- the agent remained available for follow-up,
- the follow-up materially improved the usefulness of the result,
- the main session stayed understandable,
- lifecycle cleanup was clear and controlled.

## Success criteria

A strong run should show all of the following:
- a visible todo plan,
- a meaningful mainline task,
- creation and reuse of a persistent read-only sub-agent,
- at least one useful follow-up prompt,
- delegated findings that remain understandable and bounded,
- targeted verification actually executed if main-session code changed,
- an honest final summary that distinguishes mainline results from persistent
  agent findings.

## Failure criteria

The run should be considered weak or failed if any of the following occur:
- the persistent agent is no more useful than a one-shot agent would have been,
- follow-up prompts add little or no value,
- the agent becomes confusing to track or clean up,
- verification is skipped or only claimed without evidence,
- the final summary obscures what was learned before versus after follow-up,
- the workflow devolves into noisy agent management rather than useful coding
  progress.

## Measurement guidance

Record the following in the run file:
- whether a todo plan was created,
- whether a persistent agent was created,
- how many follow-up prompts were sent,
- whether the agent remained available for follow-up,
- delegated outcome mix,
- whether follow-up improved result quality,
- whether the agent required explicit kill,
- whether mainline work continued productively,
- number of files changed,
- whether tests were modified,
- total tool-call count,
- approximate peak tool-call depth,
- time to completion,
- verification command and outcome,
- qualitative scores for plan quality, progress visibility, failure honesty,
  resume clarity, and delegation usefulness.

## Suggested verification discipline

Verification should focus on any main-session code changes and on whether the
persistent-agent workflow remained operationally clear.

Good verification examples:
- focused unit-test execution,
- narrow integration verification,
- project-specific commands that exercise the changed behavior,
- evidence that follow-up prompts received coherent responses.

Avoid claiming success based only on:
- agent availability,
- existence of a follow-up prompt,
- plausible delegated reasoning without any operational evidence.

## Evidence to retain

Retain at minimum:
- exact initial prompt,
- persistent-agent creation prompt,
- follow-up prompt or prompts,
- completed run record,
- resulting diff if code changed,
- verification command and outcome,
- final summary provided at the end of the run.

Also retain:
- what the first delegated result contained,
- what the follow-up changed or clarified,
- whether the agent stayed available,
- how the agent was cleaned up.

If the run goes poorly, also retain:
- where lifecycle confusion appeared,
- whether follow-up added overhead rather than value,
- whether the persistent workflow remained understandable to an operator.

## Recommended scoring expectations

For a healthy persistent-agent benchmark, a strong outcome would usually look
like:
- Plan quality: `2`
- Progress visibility: `1` or `2`
- Failure honesty: `2`
- Resume clarity: `1`
- Delegation usefulness: `2`

These are not required target scores. They are only sanity-check expectations
for a successful early benchmark-quality run.

## Post-run update steps

After execution:
1. create or complete a non-example run record for Scenario 6,
2. update `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`,
3. record whether persistence improved usefulness compared with one-shot
   delegation,
4. note any lifecycle or cleanup confusion,
5. identify whether the outcome changes persistent-agent workflow priorities.

## Notes for reviewers

When reviewing the run, compare:
- the initial prompt,
- the persistent-agent scope,
- the first delegated result,
- the follow-up prompt and result,
- the final diff if code changed,
- the verification evidence,
- the final summary.

The most important question is whether Monitor behaved like a trustworthy
orchestrator using persistence for a real advantage rather than as unnecessary
complexity.
