# CHECKLIST_LONG_HORIZON

Working checklist for validating and improving long-horizon coding and agentic
task support in Monitor. This checklist is organized around what must be true
for the system to be trustworthy during extended, multi-step, multi-turn work.

Use `[x]` for complete, `[ ]` for incomplete, and prefer updating this file over
creating near-duplicate task notes.

## 0. Planning and continuity
- [x] Session-scoped todo tools exist (`add_todo`, `list_todos`, `update_todo`,
      `delete_todo`, `clear_todos`).
- [x] Todo items have stable IDs.
- [x] Todo items support status tracking.
- [x] Todo items support priority ordering.
- [x] Todo storage has a persistence layer with in-memory fallback.
- [x] System prompt instructs the model to use todos for multi-step work.
- [ ] Validate long-turn resume behavior after user interruption and later
      continuation in the same session.
- [ ] Validate cross-session expectations explicitly in docs: what survives and
      what does not.

## 1. Long autonomous tool-use chains
- [x] `MAX_TOOL_CALL_DEPTH` is explicitly configured for substantial workflows.
- [x] Loop-detection guard exists for repeated identical tool calls.
- [ ] Verify representative long coding workflows stay comfortably below the
      configured depth limit.
- [ ] Identify and document common failure patterns in long tool-call chains.
- [x] Add benchmark scenarios specific to long-horizon coding loops (`docs/cache/BENCHMARKS_LONG_HORIZON.md`).

## 2. Agent orchestration availability
- [x] `agent_create` exists.
- [x] `agent_send` exists.
- [x] `agent_gather` exists.
- [x] `agent_kill` exists.
- [x] `agent_list` exists.
- [x] `agent_logfile` exists.
- [x] Orchestration is gated by `MONITOR_ENABLE_AGENT_ORCHESTRATION`.
- [ ] Document a recommended production-like enablement profile.
- [ ] Validate user-facing behavior when orchestration is disabled but the model
      attempts delegated work.

## 3. Background execution model
- [x] Spawned sub-agents run in `--agent` mode.
- [x] Async fire-and-continue guidance exists in the system prompt.
- [x] Background output can be surfaced during interactive prompting.
- [x] Terminal agent results are recorded in the orchestrator registry.
- [x] Pending next-turn injections exist for async completion notices.
- [x] Main-thread folding of agent injections into next-turn LLM prefixes
      exists.
- [ ] Validate that async completion notices remain concise under heavy usage.
- [ ] Validate multiple concurrent completions landing between user turns.

## 4. Lifecycle and liveness
- [x] Heartbeats exist.
- [x] Heartbeat timeout exists.
- [x] Dirty disconnect detection exists.
- [x] Idle timeout exists for persistent agents.
- [x] Idle reaping exists.
- [x] One-shot agents are the default.
- [x] Persistent agents are opt-in.
- [ ] Validate operational behavior for very long-running but low-output tasks.
- [ ] Validate that persistent agents are easy to identify and clean up.
- [ ] Expand follow-up coverage for persistent `agent_send(...)` workflows.

## 5. Safety bounds
- [x] Recursion depth is bounded.
- [x] Breadth is bounded.
- [x] Total spawned agents are bounded.
- [x] Conservative defaults are used.
- [x] Delegated write access is explicit.
- [x] Delegated write scope can be restricted.
- [x] Sub-agent write policy fails closed when authority is missing.
- [ ] Validate that bounds are surfaced clearly to operators and contributors.
- [ ] Add docs for choosing safe cap values by workload type.

## 6. Failure honesty
- [x] `agent_gather` returns `ok` / `failed` / `pending` buckets.
- [x] Never-connected agents surface as failure.
- [x] Dirty disconnect surfaces as failure.
- [x] Error frames surface as failure.
- [x] Timeout surfaces as pending.
- [ ] Document failure-handling guidance for orchestrator behavior after partial
      success or partial failure.
- [ ] Validate that failure notices injected into later turns are consistently
      actionable and not overly verbose.

## 7. File-mutation model
- [x] The architecture strongly prefers the orchestrator as the main writer.
- [x] Delegated writes are not the default path.
- [x] Delegated-write policy is enforced in `--agent` mode.
- [ ] Make the researcher-vs-worker policy explicit in runtime docs.
- [ ] Audit which tool surfaces are actually available to sub-agents when they
      are intended to remain read-only.
- [ ] Validate there are no silent paths that allow broad writes when only
      limited delegated scope was intended.

## 8. Human visibility and operator trust
- [x] Agent status can be rendered live.
- [x] Agent output can be surfaced above the prompt.
- [x] Agent logs remain available.
- [ ] Validate that long-running background activity is understandable to a
      human operator without log diving.
- [ ] Validate prompt responsiveness while multiple agents are active.
- [ ] Add recommendations for how much live output is too much.

## 9. Documentation quality
- [x] Working design docs exist for orchestration.
- [x] Long-horizon overview doc exists (`PLAN_LONG_HORIZON.md`).
- [x] Long-horizon behavior spec exists (`SPEC_LONG_HORIZON.md`).
- [x] Adjacent orchestration cache docs have been refreshed for consistency.
- [x] Add a practical operator setup guide for long-horizon usage (`docs/LONG_HORIZON_OPERATOR_GUIDE.md`).
- [ ] Add a contributor guide for extending long-horizon support safely.
- [ ] Summarize stable conclusions into primary docs under `docs/` when ready.

## 10. Near-term implementation order
- [x] Add a practical operator guide for bounded orchestration usage.
- [ ] Improve visibility into active background work.
- [x] Add benchmark tasks for representative long-horizon coding workflows (`docs/cache/BENCHMARKS_LONG_HORIZON.md`).
- [ ] Add stronger tests for persistent-agent follow-up flows.
- [ ] Tighten async completion notice formatting and length discipline.
- [x] Add a benchmark gaps summary (`docs/cache/BENCHMARK_GAPS_LONG_HORIZON.md`).
- [x] Add a benchmark execution queue (`docs/cache/BENCHMARK_EXECUTION_QUEUE_LONG_HORIZON.md`).
- [x] Add a long-horizon docs index (`docs/cache/INDEX_LONG_HORIZON.md`).
- [x] Add a benchmark execution playbook (`docs/cache/BENCHMARK_PLAYBOOK_LONG_HORIZON.md`).
- [x] Add persistent-agent follow-up benchmark execution scaffolding (`docs/cache/BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B_EXAMPLE.md`).
- [ ] Document failure-handling patterns for partial delegated success/failure.
- [ ] Document researcher-vs-worker mode explicitly.

## 11. Mid-term architecture improvements
- [ ] Structured artifact passing between sub-agents and orchestrator.
- [ ] Richer task dependency tracking beyond flat todos.
- [ ] Durable execution checkpoints.
- [ ] Retry and resume semantics for failed delegated work.
- [ ] Stronger cross-session project memory.
- [ ] Stronger delegated-write observability.
- [ ] Better observability surfaces for long-running work.
- [ ] Delegated cost accounting.
- [x] Better benchmarking of multi-turn, multi-agent coding tasks (`docs/cache/BENCHMARKS_LONG_HORIZON.md`, `docs/cache/BENCHMARK_RUN_TEMPLATE_LONG_HORIZON.md`).

## 12. Highest-value changes for autonomous coding quality
- [ ] Durable checkpoints and resume semantics.
- [ ] Structured sub-agent result artifacts.
- [ ] Project-scoped durable memory.
- [ ] Richer plan and task structure.
- [ ] Stronger delegated execution boundaries.
- [ ] Worktree or sandbox isolation for write-capable delegated tasks.
- [ ] A dedicated long-horizon benchmark suite.

## Exit criteria for “strong long-horizon support”
- [ ] A multi-file feature can be planned, executed, tested, and resumed over
      multiple turns with visible progress and minimal confusion.
- [ ] Independent investigation tasks can be delegated in the background while
      the orchestrator continues foreground work.
- [ ] Partial failures are surfaced clearly without corrupting the user’s sense
      of progress.
- [ ] Operators can safely tune orchestration caps for more ambitious workloads.
- [ ] Contributors can extend the system without weakening safety bounds or
      observability.
