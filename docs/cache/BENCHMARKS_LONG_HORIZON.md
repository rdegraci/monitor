# BENCHMARKS_LONG_HORIZON

Phase 2 benchmark plan for validating long-horizon coding and agentic task
support in Monitor.

This document defines representative benchmark scenarios, evaluation metrics,
run guidance, and result-capture structure for testing Monitor under realistic
long-horizon workloads. It is intended to turn the roadmap and checklist items
for Phase 2 into repeatable validation work.

## Goal

Validate that Monitor can sustain realistic long-horizon coding workflows with:
- explicit planning,
- multi-step tool-use chains,
- read/edit/test loops,
- bounded delegated background work,
- honest failure surfacing,
- useful progress visibility,
- practical resume behavior after interruption.

## Scope

These benchmarks are designed to evaluate the current architecture honestly.
They should test the system as a bounded orchestrator with optional sub-agent
support, not as an unconstrained autonomous swarm.

The benchmark plan focuses on:
- single-session multi-step coding work,
- bounded orchestration under realistic caps,
- partial failure and interruption behavior,
- operator-visible progress,
- throughput and reliability under representative workloads.

The benchmark plan does not attempt to validate:
- unconstrained recursive delegation,
- large-scale parallel repo mutation,
- filesystem rollback semantics,
- perfect unattended autonomy.

## Benchmark principles

1. **Use representative coding tasks**
   - prefer tasks that resemble real development work,
   - avoid toy prompts that do not exercise planning or verification.

2. **Keep workloads reproducible**
   - each benchmark should define setup, prompt, caps, and expected artifacts,
   - each run should be recordable in a consistent template.

3. **Measure behavior, not just success**
   - completion alone is not enough,
   - benchmark runs should capture progress quality, delegation quality, and
     recovery behavior.

4. **Test bounded orchestration explicitly**
   - benchmark default-safe profiles and modestly expanded profiles,
   - avoid treating unsupported autonomy modes as failures of the design.

5. **Prefer comparable tasks over synthetic stress alone**
   - stress tests are useful, but realistic engineering loops matter more.

## Recommended runtime profiles

### Profile A — no orchestration
Use to benchmark the baseline orchestrator without background delegation.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=0`
- `SUBAGENT_WRITE_ACCESS=none`

### Profile B — bounded research delegation
Use to benchmark the recommended long-horizon operating mode.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=none`

### Profile C — constrained delegated writing
Use only for explicitly delegated-write benchmark scenarios.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=delegated`

## Primary metrics

### Outcome metrics
- **Task completion rate**
  - Did the task reach the requested end state?
- **Verification pass rate**
  - Did the relevant tests or validation commands pass?
- **Recovery completion rate**
  - After interruption or partial failure, did the run recover and complete?

### Execution metrics
- **Tool-call depth consumption**
  - Approximate peak tool-call depth used during the run.
- **Tool-call count**
  - Total tool invocations used to complete the task.
- **Time-to-completion**
  - Wall-clock time from task start to verified completion.
- **Delegation usage**
  - Number of sub-agents created, gathered, killed, or left pending.

### Delegation quality metrics
- **Delegated task success/failure mix**
  - Count of `ok`, `failed`, and `pending` delegated outcomes.
- **Delegation usefulness**
  - Did sub-agent results materially help the main task?
- **Delegation overhead**
  - Did delegation reduce or increase task completion time and complexity?

### Operator-trust metrics
- **Plan quality**
  - Was an explicit todo plan created for non-trivial work?
- **Progress visibility quality**
  - Could an operator understand what was happening without transcript
    archaeology?
- **Failure honesty**
  - Were failures surfaced clearly and classified correctly?
- **Resume clarity**
  - After interruption, was it clear what had already completed and what had
    not?

## Scoring guidance

Use a simple 0 to 2 rubric for qualitative dimensions.

- `0` = poor or missing
- `1` = partially adequate
- `2` = strong and clearly useful

Apply this rubric to:
- plan quality,
- progress visibility,
- failure honesty,
- resume clarity,
- delegation usefulness.

## Benchmark scenario set

The benchmark suite should include at least the following scenario classes.

### Scenario 1 — single-session multi-file feature

**Purpose:**
Validate plan creation, multi-step implementation, verification, and completion
without relying on delegation.

**Expected behaviors:**
- explicit todo plan,
- orderly read/edit/test loop,
- clear progress updates,
- verified completion.

**Suggested shape:**
- change multiple files,
- update tests,
- run targeted verification,
- finish within one bounded session.

**Recommended profile:**
- Profile A
- Profile B

### Scenario 2 — investigate-then-fix bug workflow

**Purpose:**
Validate whether Monitor can sustain a realistic debugging flow instead of
jumping straight to edits.

**Expected behaviors:**
- investigation before mutation,
- hypothesis refinement,
- targeted edits,
- verification after the fix.

**Suggested shape:**
- reproduce a failing test,
- inspect relevant files,
- apply a focused fix,
- rerun verification.

**Recommended profile:**
- Profile A
- Profile B

### Scenario 3 — background audit plus foreground implementation

**Purpose:**
Validate useful bounded delegation while the orchestrator continues foreground
work.

**Expected behaviors:**
- orchestrator keeps mainline progress moving,
- one or more sub-agents perform independent research or audit work,
- delegated findings are surfaced later and incorporated usefully,
- operator can understand concurrent progress.

**Suggested shape:**
- main task modifies a core path,
- background agent audits adjacent files or searches for related risks,
- main run synthesizes delegated results before finishing.

**Recommended profile:**
- Profile B

### Scenario 4 — partial delegated failure

**Purpose:**
Validate honest failure handling when one delegated branch succeeds and another
fails or times out.

**Expected behaviors:**
- success, failure, and pending states are distinguished correctly,
- the main task does not stall unnecessarily,
- useful delegated results remain usable,
- the final summary reflects the mixed outcome honestly.

**Suggested shape:**
- spawn two bounded background tasks,
- make one intentionally fragile or timeout-prone,
- verify that failure is visible and non-blocking when appropriate.

**Recommended profile:**
- Profile B

### Scenario 5 — interruption and resume in the same session

**Purpose:**
Validate practical long-turn continuity after context switching or user
interruption.

**Expected behaviors:**
- todo state remains available,
- current progress is reconstructable,
- resumed execution does not silently repeat or skip major steps,
- completion remains achievable after resumption.

**Suggested shape:**
- begin a multi-step task,
- stop after a meaningful intermediate state,
- resume in a later turn using existing plan state,
- complete and verify the task.

**Recommended profile:**
- Profile A
- Profile B

### Scenario 6 — persistent-agent follow-up workflow

**Purpose:**
Validate whether a persistent sub-agent can support a focused, multi-turn side
investigation usefully.

**Expected behaviors:**
- persistent agent stays available for follow-up,
- follow-up prompts narrow or extend the investigation,
- lifecycle remains legible and controllable,
- results remain concise and actionable.

**Suggested shape:**
- create a persistent research agent,
- send at least one follow-up,
- gather or inspect result state,
- terminate cleanly if still active.

**Recommended profile:**
- Profile B

### Scenario 7 — delegated-write boundary validation

**Purpose:**
Validate that delegated-write behavior remains explicit, constrained, and
observable when enabled.

**Expected behaviors:**
- sub-agent write attempts fail closed when not granted,
- granted delegated writes remain scoped,
- the orchestrator retains writer-of-record clarity,
- boundary violations are visible.

**Suggested shape:**
- run a read-only delegated task,
- run an explicitly granted delegated-write task,
- compare behavior and observability.

**Recommended profile:**
- Profile C

## Suggested benchmark matrix

Use a matrix that spans capability classes and runtime profiles.

| Scenario | A: No orchestration | B: Bounded delegation | C: Delegated writes |
| --- | --- | --- | --- |
| 1. Multi-file feature | Yes | Yes | No |
| 2. Investigate then fix | Yes | Yes | No |
| 3. Background audit + foreground work | No | Yes | No |
| 4. Partial delegated failure | No | Yes | No |
| 5. Interruption and resume | Yes | Yes | No |
| 6. Persistent-agent follow-up | No | Yes | No |
| 7. Delegated-write boundary validation | No | No | Yes |

## Result capture template

Use `docs/cache/BENCHMARK_RUN_TEMPLATE_LONG_HORIZON.md` for each benchmark run.
Use `docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md` for end-to-end execution guidance.

Starter example records currently exist at:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_3_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_4_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_5_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B_EXAMPLE.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_7_PROFILE_C_EXAMPLE.md`

Planned real-run records currently exist at:
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_3_PROFILE_B.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_4_PROFILE_B.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_5_PROFILE_B.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B.md`
- `docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_7_PROFILE_C.md`

## Evidence to retain

For meaningful runs, retain:
- the initial prompt,
- the final summary,
- the resulting diff if code changed,
- verification output,
- delegated result summary,
- relevant logs for failures or lifecycle issues.

Where possible, store benchmark results in a stable directory or issue tracker
so future runs can be compared over time.

## Prioritized implementation order

The benchmark program should be built in this order:

1. Scenario 1 — single-session multi-file feature
2. Scenario 2 — investigate-then-fix bug workflow
3. Scenario 5 — interruption and resume in the same session
4. Scenario 3 — background audit plus foreground implementation
5. Scenario 4 — partial delegated failure
6. Scenario 6 — persistent-agent follow-up workflow
7. Scenario 7 — delegated-write boundary validation

This order starts with the most representative core workflows, then adds
bounded delegation and failure-path coverage.

## Exit criteria for Phase 2

Phase 2 should be considered substantively complete when:
- representative benchmark scenarios are defined and documented,
- at least one reproducible fixture exists for each core scenario class,
- benchmark runs have been executed and recorded for Profiles A and B,
- delegated-write boundary validation has been executed for Profile C,
- bottlenecks and recurring failure modes are summarized in a follow-up doc,
- roadmap prioritization can reference benchmark evidence rather than only
  architectural inspection.

## Relationship to other long-horizon docs

This benchmark plan operationalizes the following documents:
- `docs/cache/ROADMAP_LONG_HORIZON.md`
- `docs/cache/PLAN_LONG_HORIZON.md`
- `docs/cache/CHECKLIST_LONG_HORIZON.md`
- `docs/cache/SPEC_LONG_HORIZON.md`

It should be updated when benchmark fixtures, result locations, or scoring
criteria become more concrete.

Executed benchmark results should be indexed in
`docs/cache/BENCHMARK_RESULTS_LONG_HORIZON.md`.
