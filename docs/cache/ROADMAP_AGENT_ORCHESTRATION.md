# Roadmap: Agent Orchestration (src/monitor/)

Phased roadmap for the orchestration stack as it exists today. This refresh
starts from current implementation reality rather than the earlier greenfield
plan.

## Current baseline

The codebase already has:
- real `monitor --agent` child spawning,
- AF_UNIX frame transport,
- child reporting via `agent_reporter`,
- orchestrator listener and registry,
- live prompt and TUI visibility,
- async next-turn result injection,
- `agent_gather(...)`,
- one-shot default lifecycle plus persistent opt-in,
- heartbeat timeout and idle reaping,
- delegated-write policy enforcement,
- bounded breadth, total, and depth controls.

So the roadmap now focuses on **hardening, clarity, observability, and richer
operator experience**, not basic existence.

## Phase 0 — Baseline alignment
**Goal:** Make all orchestration docs describe the current architecture
accurately.

- Refresh cache docs to match current code reality.
- Distinguish implemented behavior from future work.
- Document bounded orchestration rather than unconstrained autonomy.
- Clarify that failure handling is not filesystem rollback.

**Exit criteria:**
- top-level docs are internally consistent,
- contributors can tell what is already implemented,
- no major orchestration doc materially contradicts current code.

## Phase 1 — Operator guidance
**Goal:** Make the current orchestration system easy to use safely.

- Add a practical guide for enabling orchestration.
- Document conservative defaults and recommended cap profiles.
- Explain one-shot vs persistent agent usage.
- Explain when to use `agent_gather(...)` and when not to.
- Explain delegated-write modes and risk tradeoffs.

**Exit criteria:**
- a contributor can configure bounded orchestration confidently,
- a user can understand how background delegation behaves,
- lifecycle and write policy tradeoffs are explicit.

## Phase 2 — Validation and benchmarks
**Goal:** Prove orchestration behavior under realistic workloads.

- Add scenarios covering:
  - background audit while foreground work continues,
  - multiple terminal completions between user turns,
  - partial failure and timeout behavior,
  - persistent follow-up workflows,
  - delegated-write policy enforcement.
- Benchmark responsiveness and output quality under bounded fan-out.

**Exit criteria:**
- representative orchestration workflows are reproducible,
- regressions become measurable,
- future improvements can be prioritized using evidence.

## Phase 3 — Better observability
**Goal:** Improve operator trust during long-running delegated work.

- Add better summaries for active background work.
- Improve visibility into recently completed and failed agents.
- Surface heartbeat and idle state more clearly where useful.
- Keep prompt responsiveness acceptable while improving visibility.

**Exit criteria:**
- operators can understand what is happening at a glance,
- failures are easier to diagnose,
- active-work visibility is better than raw log inspection.

## Phase 4 — Stronger persistent-agent ergonomics
**Goal:** Make persistent agents safer and easier to use.

- Expand follow-up tests for `agent_send(...)` workflows.
- Improve documentation around cleanup expectations.
- Clarify persistent-agent operator patterns.
- Verify idle reaping behavior under more realistic usage patterns.

**Exit criteria:**
- persistent-agent usage is well covered by tests,
- contributors understand the intended lifecycle,
- idle and follow-up behavior are less error-prone.

## Phase 5 — Richer result artifacts
**Goal:** Improve orchestrator consumption of delegated work.

- Standardize concise structured result shapes.
- Make delegated results easier to summarize and aggregate.
- Reduce transcript-like result payloads.
- Improve async injected completion summaries.

**Exit criteria:**
- background findings are easier for the orchestrator to reuse,
- next-turn injections stay concise,
- context-window pressure from delegation is reduced.

## Phase 6 — Stronger policy clarity and enforcement
**Goal:** Tighten the researcher-vs-worker boundary.

- Document researcher vs worker mode explicitly.
- Audit actual write-capable tool surfaces available to sub-agents.
- Improve visibility into delegated grants and scopes.
- Revisit whether additional defense-in-depth depth checks are worthwhile.

**Exit criteria:**
- delegated mutation authority is easier to reason about,
- contributor understanding of safe delegation improves,
- safety policy becomes easier to audit.

## Phase 7 — Advanced scaling decisions
**Goal:** Evaluate whether more ambitious orchestration is warranted.

- Revisit whether broader fan-out is justified.
- Consider aggregated child cost accounting.
- Consider stronger isolation if write-capable delegation expands.
- Avoid broadening autonomy without observability and benchmark support.

**Exit criteria:**
- any increase in orchestration ambition is evidence-based,
- scaling does not weaken safety guarantees,
- the single-writer design center is preserved unless deliberately revised.

## Recommended priority order

1. baseline alignment,
2. operator guidance,
3. validation and benchmarks,
4. observability,
5. persistent-agent ergonomics,
6. richer result artifacts,
7. stronger policy clarity.

## Non-goals for now

This roadmap does not assume immediate pursuit of:
- unconstrained recursive orchestration,
- large swarms of concurrent repo writers,
- hidden autonomous merge workflows,
- filesystem rollback of delegated side effects.

## Relationship to long-horizon roadmap

This roadmap is intentionally narrower than `ROADMAP_LONG_HORIZON.md`.

Use this document for sub-agent-stack-specific work such as reporting,
lifecycle, observability, and delegated-write policy. Use the long-horizon
roadmap for broader planning, continuity, and autonomous coding quality work.

## Bottom line

The orchestration stack already exists.

The next work should focus on:
- making it clearer,
- validating it under realistic load,
- improving operator trust,
- only then expanding the autonomy envelope.
