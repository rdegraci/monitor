# BENCHMARK_PLAYBOOK_LONG_HORIZON

Operator playbook for executing Phase 2 long-horizon benchmarks in Monitor.

This document explains how to prepare a benchmark fixture, choose a runtime
profile, execute a benchmark run, capture evidence, and summarize results into
the long-horizon benchmark tracking docs.

It pairs with:
- `docs/cache/INDEX_LONG_HORIZON.md`
- `docs/cache/BENCHMARKS_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_EXECUTION_QUEUE_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RUN_TEMPLATE_LONG_HORIZON.md`
- `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`
- the scenario-specific benchmark run records in `docs/cache/`

## Purpose

Use this playbook when you want to:
- execute a real benchmark run,
- make runs comparable across operators,
- avoid inconsistent evidence capture,
- reduce ambiguity about what to record,
- turn benchmark execution into roadmap-relevant evidence.

## Benchmark execution goals

A useful benchmark run should do all of the following:
- exercise a realistic long-horizon workflow,
- use a clearly declared runtime profile,
- preserve the exact prompt and outcome record,
- capture verification evidence,
- capture failures honestly,
- leave behind enough artifacts for later comparison.

## Before you run a benchmark

### 1. Choose the scenario

Pick one scenario from `docs/cache/BENCHMARKS_LONG_HORIZON.md`:
- Scenario 1 — single-session multi-file feature
- Scenario 2 — investigate-then-fix bug workflow
- Scenario 3 — background audit plus foreground implementation
- Scenario 4 — partial delegated failure
- Scenario 5 — interruption and resume in the same session
- Scenario 6 — persistent-agent follow-up workflow
- Scenario 7 — delegated-write boundary validation

Choose a task shape that is representative, not artificially easy.

### 2. Choose the runtime profile

Use the profile recommended by the benchmark plan.

- **Profile A** — no orchestration
- **Profile B** — bounded research delegation
- **Profile C** — constrained delegated writing

Record the exact configuration in the run record.

### 3. Choose the repo fixture

The fixture should:
- be stable enough to rerun later,
- contain the conditions needed for the scenario,
- have a clear verification path,
- avoid unrelated repo churn.

If possible, use a clean branch dedicated to benchmark execution.

### 4. Create or select the run record

Use one of these approaches:
- fill in an existing planned real-run record,
- copy the generic template into a new run file,
- create a new run ID and add it to the results index before execution.

Recommended current starting points:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md`

### 5. Prepare artifact capture

Before execution, decide where you will retain:
- verification output,
- git diff,
- terminal summary,
- agent logs where applicable,
- notes on failures or interruptions.

Do not rely on memory after the fact.

## Recommended pre-run checklist

- [ ] Scenario selected
- [ ] Runtime profile selected
- [ ] Repo fixture selected
- [ ] Clean or intentionally prepared branch confirmed
- [ ] Run record file ready
- [ ] Results index entry ready or planned
- [ ] Verification commands chosen
- [ ] Artifact storage location chosen
- [ ] Special failure or interruption conditions planned if applicable

## Running the benchmark

### Step 1. Record starting context

Before the benchmark begins, record:
- date,
- branch or commit,
- scenario ID,
- runtime profile,
- operator,
- exact initial prompt.

Exact prompt preservation matters for repeatability.

### Step 2. Start with the intended runtime profile

Apply the profile settings exactly.

Examples:

#### Profile A
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=0`
- `SUBAGENT_WRITE_ACCESS=none`

#### Profile B
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=none`

#### Profile C
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=delegated`

### Step 3. Run the scenario faithfully

Let the task naturally exercise the intended behavior.

Examples:
- Scenario 1 should emphasize planning, editing, and verification.
- Scenario 3 should allow the orchestrator to continue foreground work while a
  background task runs.
- Scenario 4 should include a mixed delegated outcome.
- Scenario 5 should include a real interruption point and later resumption.
- Scenario 6 should include at least one persistent-agent follow-up.
- Scenario 7 should include both denied and allowed delegated-write attempts.

Do not simplify the task mid-run just to force success unless you record that
change explicitly.

### Step 4. Capture observations during execution

Record key facts while the run is active:
- whether a todo plan was created,
- whether delegation happened,
- whether failure surfaced clearly,
- whether progress remained understandable,
- whether the task stayed within a reasonable tool-call envelope,
- whether verification actually ran.

Capture observations contemporaneously whenever possible.

### Step 5. Preserve verification evidence

At the end of the run, preserve:
- verification command lines,
- pass or fail status,
- relevant output,
- resulting diff,
- notes on residual risks.

If verification could not be completed, record why.

## Scenario-specific guidance

### Scenario 1 — single-session multi-file feature

Focus on:
- todo usage,
- orderly implementation flow,
- clean verification,
- final summary quality.

Red flags:
- no explicit plan for a clearly non-trivial task,
- shallow or skipped verification,
- repeated looping without progress.

### Scenario 2 — investigate-then-fix bug workflow

Focus on:
- actual reproduction or inspection before edits,
- root-cause reasoning quality,
- precision of the fix,
- test validation after the fix.

Red flags:
- edits before meaningful investigation,
- weak linkage between diagnosis and fix,
- incomplete verification.

### Scenario 3 — background audit plus foreground implementation

Focus on:
- useful task decomposition,
- foreground progress while delegation is active,
- value of delegated results,
- clarity of operator-visible progress.

Red flags:
- blocking on delegation without need,
- delegated task too tightly coupled to foreground work,
- opaque or noisy concurrent progress.

### Scenario 4 — partial delegated failure

Focus on:
- accurate classification of mixed outcomes,
- ability to continue useful work despite failure,
- clarity of failure messaging,
- honesty of final summary.

Red flags:
- failed work mislabeled as success,
- successful delegated results becoming unusable,
- unnecessary mainline stall.

### Scenario 5 — interruption and resume

Focus on:
- whether todo state survives clearly,
- how easy it is to reconstruct status,
- whether resumed work avoids repetition and omission,
- whether final completion remains orderly.

Red flags:
- confusion about what already completed,
- resume behavior requiring transcript archaeology,
- accidental rework or skipped steps.

### Scenario 6 — persistent-agent follow-up

Focus on:
- persistent agent availability,
- usefulness of follow-up prompts,
- lifecycle clarity,
- clean cleanup behavior.

Red flags:
- follow-up messages failing unexpectedly,
- persistent state becoming confusing,
- cleanup burden on the operator.

### Scenario 7 — delegated-write boundary validation

Focus on:
- fail-closed denied writes,
- scoped success for allowed writes,
- clear writer-of-record behavior,
- observability of grants and denials.

Red flags:
- silent broad writes,
- unclear scope enforcement,
- weak auditability of granted authority.

## After the run

### 1. Complete the run record

Fill in all relevant sections of the run file:
- metadata,
- observed execution,
- verification outcome,
- qualitative scores,
- interruptions or failures,
- final assessment.

Do not leave ambiguous fields blank if the information is known.

### 2. Update the results index

In `docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`:
- update the run index row,
- link the completed run record,
- update the appropriate scenario summary,
- update the appropriate profile summary,
- add any recurring bottlenecks or follow-up actions.

### 3. Note roadmap implications

If the run reveals a clear pattern, connect it back to roadmap priorities.

Examples:
- repeated resume confusion supports Phase 3 work,
- weak delegated artifact usefulness supports Phase 5 work,
- poor visibility under concurrent activity supports Phase 7 work.

## Suggested scoring discipline

Use the 0 to 2 rubric consistently.

- `0` = poor or absent
- `1` = mixed or partial
- `2` = strong and clearly useful

When scoring:
- justify unusually high or low scores in notes,
- avoid giving all dimensions the same score by default,
- distinguish successful completion from high-quality execution.

## Evidence retention guidance

Retain enough evidence that another contributor can review the run later.

Minimum recommended evidence:
- initial prompt,
- completed run record,
- verification command and outcome,
- final summary,
- diff for code-changing runs.

Additional evidence when applicable:
- agent logs,
- failure output,
- interruption notes,
- gather results,
- screenshots or copied status output if UI visibility is relevant.

## Common mistakes to avoid

- treating a planned run as an executed run,
- losing the exact prompt,
- failing to record runtime configuration,
- marking verification as passed without preserving evidence,
- smoothing over partial failure,
- changing scenario shape mid-run without documenting it,
- conflating benchmark scaffolding with actual benchmark evidence.

## Recommended first execution order

For the first real runs, use this order:
1. Scenario 1 / Profile A
2. Scenario 2 / Profile B
3. Scenario 5 / Profile B
4. Scenario 3 / Profile B
5. Scenario 4 / Profile B
6. Scenario 6 / Profile B
7. Scenario 7 / Profile C

This order starts with the most interpretable core workflows before moving into
more failure-sensitive or boundary-sensitive scenarios.

## Exit criteria for using this playbook well

The playbook is being used effectively when:
- multiple operators can produce comparable run records,
- benchmark evidence is preserved consistently,
- scenario summaries in the results index become easy to maintain,
- roadmap discussions can point to real benchmark outcomes rather than only
  architectural reasoning.
