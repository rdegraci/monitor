# SPEC_LONG_HORIZON

Working behavior spec for long-horizon coding support in Monitor.

This document defines the current behavioral contract for planning,
delegation, continuity, visibility, and bounded autonomy when Monitor is used
for extended coding tasks. It is intentionally implementation-aware enough to
stay honest about what exists today, while still serving as a stable contract
for future work.

## Scope

This spec covers:
- multi-step coding work,
- multi-turn continuity,
- delegated background work through sub-agents,
- progress tracking and visibility,
- safety constraints that intentionally limit autonomy,
- delegated-write policy boundaries.

This spec does not define:
- the low-level frame wire format in full detail,
- exact UI rendering behavior,
- provider-specific tool-call formats,
- filesystem rollback semantics,
- full durable cross-session project memory.

Those are specified elsewhere or remain implementation details.

## Definitions

### Long-horizon task
A task that requires one or more of the following:
- multiple coding steps,
- work across multiple files,
- work across multiple user turns,
- investigation before edits,
- verification after edits,
- delegated background work.

### Orchestrator
The primary Monitor session coordinating user interaction, tool use, plan
tracking, and any sub-agent delegation.

This is the primary long-horizon actor in the system. It owns continuity,
planning, delegation decisions, result collation, and the writer-of-record
role.

### Sub-agent
A spawned Monitor instance running in `--agent` mode, usually performing one
focused delegated task and reporting results back to the orchestrator.

Sub-agents are supporting workers for the orchestrator's long-horizon loop.
By default they are researchers/proposal generators, not independent
long-horizon owners of the task.

### One-shot agent
A sub-agent that exits after completing and reporting its first task turn.

### Persistent agent
A sub-agent that remains alive for follow-up prompts until explicitly reaped,
killed, or idle-reaped.

## Behavioral requirements

### 1. Planning requirements
For long-horizon tasks, the system should maintain an explicit plan.

#### Required behavior
- The orchestrator should use the todo tools for multi-step coding work except
  in trivial one-shot cases.
- Todo items must support stable identity, status, and priority.
- The current plan must be retrievable during the session.
- Plan state must be updateable as the task evolves.

#### Non-requirement
- The system is not required to support full DAG-style task dependencies today.

### 2. Continuity requirements
The system should preserve enough state to continue meaningful work across
turns.

#### Required behavior
- Session-scoped task plans must persist for the life of the session.
- Lightweight session-scoped task context must be available for acceptance
  criteria, scope-change notes, and resume checkpoints.
- Long-running delegated work must be observable after spawn.
- Completed delegated results should be available to later orchestrator turns.
- Background delegated completions should be injectable into the next relevant
  orchestrator turn.

#### Allowed limitation
- Exact execution-state checkpointing is not currently required; lightweight
  resume checkpoints are sufficient for current conformance.

### 3. Delegation requirements
Delegation should be available for independent background work.

#### Required behavior
- The orchestrator must be able to spawn a background sub-agent.
- The spawn operation should return immediately rather than block by default.
- The orchestrator must be able to gather terminal outcomes for delegated work.
- The orchestrator must be able to terminate a sub-agent.
- Persistent sub-agents must support follow-up messages.
- One-shot sub-agents must be available as the default lifecycle.

#### Constraints
- Delegation must remain bounded by explicit caps.
- Delegation must not imply unlimited recursive agent creation.
- Delegation must not silently decide ambiguous user intent.

### 4. Visibility requirements
Long-horizon work should remain legible to a human operator.

#### Required behavior
- Active delegated work should expose visible status.
- Important sub-agent output should be visible without requiring immediate log
  inspection.
- Terminal delegated outcomes should be surfaced clearly.
- Recent delegated outcomes should be summarized compactly for the primary
  orchestrator.
- Failures should be visible and not silently dropped.
- Background completions should be surfaced both to the operator and to later
  orchestrator reasoning.

#### Allowed implementation freedom
- The exact rendering mechanism may vary.

### 5. Failure-handling requirements
Failures during long-horizon work must be represented honestly.

#### Required behavior
- Delegated work must be classifiable as success, failure, or still pending.
- Never-connected delegated work must not be treated as silent success.
- Dirty disconnects must not be treated as clean completion.
- Timeout must not be treated as success.
- Failure information should be actionable enough for the orchestrator to
  react.

#### Explicit non-guarantee
- A delegated failure does not imply rollback of filesystem mutations.

### 6. Safety-bound requirements
Long-horizon support must be bounded by configuration and policy.

#### Required behavior
- Orchestration must be gateable.
- Recursion depth must be bounded.
- Concurrent delegated breadth must be bounded.
- Total delegated count per session must be bounded.
- Delegated write authority must require explicit grant.
- Delegated write scope should be restrictable.
- Sub-agent write policy should fail closed when permission is absent or
  ambiguous.

#### Intent
These bounds are part of the design, not evidence of incompleteness.

### 7. Writer-of-record requirements
The architecture should preserve a clear writer of record.

#### Preferred behavior
- The orchestrator should remain the primary writer of repo state.
- Sub-agents should default to researcher/proposal roles unless explicit write
  authority is granted.
- Delegated writing should be exceptional and constrained.

#### Rationale
This reduces conflict risk and preserves accountability during long tasks.

### 8. Tool-use requirements
Long-horizon coding requires room for substantial tool-use sequences.

#### Required behavior
- The system must tolerate many tool-call rounds within one coding turn.
- Repeated identical tool-call loops should be detectable and rejectable.
- Guardrails should prevent infinite or pathological loop behavior.

### 9. Lifecycle requirements
Delegated workers must not linger indefinitely without control.

#### Required behavior
- One-shot workers should self-reap after completing their intended task turn.
- Persistent workers should be explicitly killable.
- Heartbeats should exist for liveness tracking.
- Idle reaping should exist for persistent workers.
- Follow-up sends to persistent workers should reject one-shot, busy, failed,
  and idle-reaped sessions rather than silently pretending the follow-up was
  accepted.

### 10. Operator expectations
The system should set accurate expectations about its own autonomy.

#### Required behavior
- Documentation should distinguish bounded orchestration from unconstrained
  autonomous engineering.
- Documentation should distinguish conversation/task continuity from
  world-state rollback.
- Documentation should communicate conservative defaults clearly.
- Documentation should communicate that orchestration is real but intentionally
  bounded.

## Acceptance examples

### Example A — multi-step feature work
A user asks for a moderate multi-file feature.

Expected compliant behavior:
- the orchestrator creates a visible todo plan,
- may set explicit acceptance criteria,
- executes investigation and edits in sequence,
- runs tests or equivalent verification,
- updates plan state as work progresses,
- adds newly discovered required work explicitly when the scope evolves,
- can continue over multiple turns without losing the plan.

### Example B — delegated background audit
A user asks for an audit spanning several independent surfaces.

Expected compliant behavior:
- the orchestrator may spawn one or more bounded background sub-agents,
- returns promptly to foreground work,
- receives sub-agent results later,
- incorporates those findings into later reasoning,
- surfaces any failures clearly.

### Example C — partial failure
One of several delegated tasks crashes.

Expected compliant behavior:
- the crash is surfaced as failure,
- successful delegated tasks remain usable,
- pending tasks are not mislabeled,
- the orchestrator can continue non-blocked work.

## Improvement classes

The following categories are useful for planning future work against this spec.

### Quick wins
These improve long-horizon usability and operator trust without requiring major
architectural change.

Examples:
- practical orchestration operator guidance,
- deferred benchmark tasks for representative long-horizon workflows,
- concise async completion notices,
- clearer failure-handling guidance,
- better active-work visibility,
- explicit researcher-vs-worker documentation,
- stronger persistent-agent workflow coverage.

### Near-term implementation focus
The initial code-facing long-horizon implementation pass has already focused
on:

1. observability for active background work,
2. persistent-agent follow-up hardening,
3. initial resume and recovery semantics.

These were the nearest improvements that strengthened trust and continuity
without requiring a richer task model or larger autonomy jump first.

These improvements primarily target the primary Monitor instance: its visible
state, its orchestration lifecycle handling, and its ability to resume after
interruption. Sub-agents remain bounded supporting workers unless explicit
delegated-write policy says otherwise.

Benchmarking is not part of this near-term implementation pass.

For feature-oriented work, the primary Monitor instance should also become more
disciplined about plan expansion and completion:
- newly discovered required work should be added to the todo plan explicitly,
- material scope growth should be surfaced rather than silently absorbed,
- "done" should be judged against acceptance criteria, not just code changes.

Those expectations now have direct runtime support via:
- `add_discovered_work`,
- `set_task_acceptance`,
- `save_task_checkpoint`,
- `get_task_context`.

### Medium-term architecture improvements
These improve the system's resilience and structural ability to sustain larger
multi-step tasks.

Examples:
- durable execution checkpoints,
- richer task structure beyond flat todos,
- structured artifact passing from sub-agents,
- retry and resume semantics for delegated work,
- project-scoped durable memory,
- improved observability and cost accounting.

### Highest-value changes for autonomous coding quality
These are the changes most likely to improve the actual quality of autonomous
coding behavior.

Examples:
- durable checkpoints and resume semantics,
- structured sub-agent result artifacts,
- project-scoped durable memory,
- richer plan and task structure,
- stronger delegated execution boundaries,
- worktree or sandbox isolation for write-capable sub-agents,
- dedicated long-horizon benchmark suites.

## Known out-of-scope enhancements

The following would strengthen long-horizon support, but are not required for
compliance with the current spec:
- durable execution checkpoints,
- cross-session project memory with rich semantics,
- task dependency graphs,
- worktree isolation for write-capable sub-agents,
- automatic retry and replay of delegated task fragments.

## Conformance statement

A Monitor build can reasonably claim support for long-horizon coding if it:
- maintains explicit plan state for non-trivial work,
- sustains extended tool-use chains,
- supports bounded delegated background work,
- surfaces delegated results and failures honestly,
- preserves operator-visible progress,
- enforces configuration and policy bounds on autonomy.

## Bottom line

The long-horizon contract for Monitor is not “do anything autonomously.”
It is:

> plan explicitly, delegate carefully, continue asynchronously, surface
> progress, and preserve bounded, trustworthy control during extended coding
> work.
