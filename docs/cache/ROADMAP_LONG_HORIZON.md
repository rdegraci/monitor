# ROADMAP_LONG_HORIZON

Phased roadmap for strengthening Monitor's long-horizon coding and agentic task
support. This roadmap starts from the current state of the codebase, where
planning, long tool-call chains, bounded agent orchestration, async result
injection, and delegated-write controls already exist, and focuses on what
would most improve trust, resilience, and throughput.

## Goal

Make Monitor stronger at:
- sustaining multi-step coding work over many turns,
- safely delegating independent background tasks,
- resuming after interruption or partial failure,
- keeping users and operators aware of progress,
- scaling ambition without losing architectural discipline.

## Phase 0 — Baseline and terminology
**Goal:** Align on what “long-horizon” means and what the current system
already supports.

- Publish a working definition of long-horizon support.
- Document existing strengths: todos, orchestration, async completions,
  lifecycle controls, caps, and delegated write controls.
- Document current limits explicitly so expectations are correct.
- Distinguish conversation continuity from filesystem rollback.

**Primary artifacts:**
- `SPEC_LONG_HORIZON.md`
- `PLAN_LONG_HORIZON.md`

**Exit criteria:**
- contributors have a shared mental model,
- the system is not oversold as unconstrained autonomy,
- the current architecture is described accurately.

## Phase 1 — Operational guidance
**Goal:** Make the existing capability easy to use safely.

- Add practical setup guidance for enabling orchestration.
- Recommend default cap profiles for common workloads.
- Document when to use todos, when to delegate, and when not to.
- Document one-shot vs persistent sub-agent usage patterns.
- Document delegated-write modes (`none`, `delegated`, `full`) and their risks.
- Document expected failure modes and how to react.

**Why this matters:**
The code already supports meaningful long-horizon work, but operators need a
clear playbook so they do not accidentally run in an unsafe or ineffective
configuration.

**Exit criteria:**
- a contributor can configure bounded orchestration confidently,
- a user can understand how long-horizon work progresses in practice,
- safe defaults and recommended overrides are clearly documented.

## Phase 2 — Validation and benchmarks
**Goal:** Prove long-horizon behavior under realistic workloads.

- Add benchmark tasks that require:
  - multi-step planning,
  - read/edit/test loops,
  - delegated background investigation,
  - partial failure handling,
  - resume behavior after interruption.
- Measure:
  - completion rate,
  - tool-call depth consumption,
  - delegated task success/failure mix,
  - operator-visible progress quality,
  - time-to-completion for bounded fan-out workflows.

**Why this matters:**
A system can look architecturally strong on inspection and still fail under
real workload pressure. Long-horizon support should be demonstrated, not merely
described.

**Exit criteria:**
- benchmark evidence exists for representative long-horizon workflows,
- bottlenecks and failure modes are reproducible,
- future work can be prioritized using data rather than intuition alone.

## Phase 3 — Resume and recovery semantics
**Goal:** Improve trust when long tasks are interrupted.

- Formalize what state survives interruption and what does not.
- Add clearer resume conventions for:
  - unfinished todo plans,
  - background delegated work,
  - partially completed coding loops.
- Introduce lightweight execution checkpoints where practical.
- Improve recovery guidance after:
  - agent timeout,
  - dirty disconnect,
  - operator interruption,
  - orchestration-cap refusal.

**Why this matters:**
Long-horizon work becomes much more useful when interruption is normal rather
than catastrophic.

**Exit criteria:**
- interrupted work can be resumed with low ambiguity,
- users retain confidence about what has and has not completed,
- delegated failure does not force full manual reconstruction of state.

## Phase 4 — Richer task model
**Goal:** Move beyond a flat todo list without abandoning simplicity.

- Add optional dependency relationships between tasks.
- Support grouping or phases within larger plans.
- Allow explicit blockers and waiting states.
- Improve prioritization semantics for plans that span investigation, coding,
  and verification.

**Why this matters:**
Flat lists work well for moderate tasks, but larger coding efforts often need a
clearer structure than simple pending/in-progress/done items.

**Exit criteria:**
- plans for medium-to-large changes remain understandable,
- the orchestrator can reason about blockers and sequencing more precisely,
- the task model remains lightweight enough for routine use.

## Phase 5 — Stronger delegated artifact flow
**Goal:** Improve handoff quality between sub-agents and the orchestrator.

- Standardize result payload structure for delegated tasks.
- Make it easier for sub-agents to return:
  - findings,
  - candidate diffs,
  - proposed test cases,
  - risk summaries,
  - file-specific recommendations.
- Add stronger guidance for concise, structured result summaries.

**Why this matters:**
Long-horizon delegation is only useful when the orchestrator can consume the
results efficiently and act on them without transcript archaeology.

**Exit criteria:**
- sub-agent outputs are consistently useful and compact,
- orchestrator synthesis gets easier,
- context-window pressure from background work decreases.

## Phase 6 — Safer delegated execution
**Goal:** Tighten confidence around delegated mutation.

- Make researcher-vs-worker policy explicit and enforceable.
- Audit which tools sub-agents can invoke under which grants.
- Improve write-scope enforcement and observability.
- Consider sandbox or worktree-based isolation for write-capable sub-agents.

**Why this matters:**
The current architecture is strongest when the orchestrator is the main writer.
If delegated writing grows, isolation and enforcement become more important.

**Exit criteria:**
- delegated write behavior is explicit, inspectable, and bounded,
- operators know when a sub-agent can mutate state,
- future scaling does not require weakening safety assumptions.

## Phase 7 — Better observability for long-running work
**Goal:** Make extended activity legible to humans.

- Improve operator-facing summaries of active background work.
- Surface progress without overwhelming the prompt.
- Provide clearer summary views for:
  - active agents,
  - completed delegated tasks,
  - failed delegated tasks,
  - unfinished plan items.
- Add practical logging and troubleshooting guidance.

**Why this matters:**
If a system can perform long-horizon work but humans cannot understand its
state, trust erodes quickly.

**Exit criteria:**
- operators can understand background activity at a glance,
- prompt responsiveness stays acceptable,
- failures are diagnosable without excessive log spelunking.

## Phase 8 — Durable project memory
**Goal:** Extend continuity beyond a single active session.

- Introduce stronger project-scoped memory for architectural facts,
  conventions, and prior decisions.
- Distinguish volatile session planning from durable project knowledge.
- Add safe mechanisms for recalling prior conclusions in later sessions.

**Why this matters:**
True long-horizon engineering work often spans days or weeks. Session-scoped
planning is valuable, but durable project memory would make the system much
stronger.

**Exit criteria:**
- important repo-level knowledge can survive beyond one session,
- future work can resume from prior architectural context,
- memory remains auditable and not silently self-expanding.

## Phase 9 — Advanced autonomous engineering support
**Goal:** Carefully expand ambition without losing control.

- Revisit whether broader fan-out is justified.
- Evaluate per-task worktrees or stronger isolation models.
- Add structured retry policies for delegated failures.
- Add richer orchestration cost accounting.
- Consider deeper autonomous job-style workflows only after prior phases are
  stable and benchmarked.

**Why this matters:**
The current design center is disciplined, bounded orchestration. More ambitious
autonomy should only be added after the foundation is measurably trustworthy.

**Exit criteria:**
- scaling up does not compromise observability,
- safety controls remain first-class,
- larger autonomous workflows have evidence behind them.

## Prioritization bands

### Quick wins

These should land first because they improve the effectiveness of the current
system without requiring major architectural change.

1. practical operator guidance,
2. long-horizon benchmark tasks,
3. tighter async completion summaries,
4. clearer failure-handling guidance,
5. explicit researcher-vs-worker documentation,
6. better active-work visibility,
7. stronger persistent-agent workflow test coverage.

### Medium-term architecture improvements

These are the most important structural upgrades once the quick wins are in
place.

1. durable execution checkpoints,
2. richer task structure beyond flat todos,
3. structured artifact passing from sub-agents,
4. retry and resume semantics for delegated work,
5. project-scoped durable memory,
6. stronger delegated-write observability,
7. better observability surfaces,
8. delegated cost accounting,
9. per-task long-horizon benchmarking tied to representative coding workflows.

### Highest-value changes for autonomous coding quality

If the goal is to improve the actual quality of autonomous coding behavior, the
highest-value changes are:

1. durable checkpoints and resume semantics,
2. structured sub-agent result artifacts,
3. project-scoped durable memory,
4. richer plan and task structure,
5. stronger delegated execution boundaries,
6. worktree or sandbox isolation for write-capable delegated tasks,
7. a dedicated long-horizon benchmark suite.

## Recommended priority order

Most likely implementation order given the current codebase:
1. operational guidance and observability,
2. validation and benchmarks,
3. persistent-agent workflow hardening,
4. richer delegated artifact flow,
5. minimal richer task-model improvements,
6. resume and recovery semantics,
7. project-scoped durable memory,
8. safer delegated execution and delegated-write observability,
9. worktree or sandbox isolation for write-capable delegation if needed,
10. broader autonomy scaling only after the earlier layers are proven.

This sequence biases toward clarity, measurement, delegation quality, and
state recovery before expanding the autonomy envelope.

## Non-goals for now

This roadmap does not assume immediate pursuit of:
- unconstrained recursive agent trees,
- large swarms of concurrent repo writers,
- hidden autonomous branching and merging workflows,
- filesystem rollback masquerading as task rollback.

Those may become interesting later, but they are not aligned with the current
architectural center of gravity.

## Bottom line

Monitor already has a credible long-horizon foundation.

The roadmap should therefore focus first on:
- making the current capability easier to operate,
- proving it under realistic workloads,
- strengthening recovery and handoff quality,
- only then widening the autonomy envelope.

Phase 1 operator guidance now lives in `docs/LONG_HORIZON_OPERATOR_GUIDE.md`.
Phase 2 benchmark planning now lives in `docs/cache/BENCHMARKS_LONG_HORIZON.md`.
Long-horizon doc navigation now lives in `docs/cache/INDEX_LONG_HORIZON.md`.
