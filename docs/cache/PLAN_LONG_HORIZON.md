# LONG_HORIZON: Long-Horizon Coding and Agentic Task Support

This document captures the current state of long-horizon coding support in the
Monitor codebase, with emphasis on planning, orchestration, runtime behavior,
safety constraints, and practical usage guidance. It is a working artifact for
developers evaluating or extending the system's ability to sustain multi-step,
multi-turn, and delegated software engineering tasks.

## Summary

Monitor supports long-horizon coding in a **bounded, safety-minded** form.
It is not just a single-turn chat CLI. The codebase contains:

- multi-step planning with session-scoped todo tools,
- long autonomous tool-use chains within a turn,
- sub-agent orchestration with background execution,
- asynchronous result harvesting into later turns,
- lifecycle controls for spawned agents,
- explicit guardrails around recursion, fan-out, and delegated writes.

The current architecture is best described as:

> a supervised orchestrator with bounded researcher/worker sub-agents,
> designed for disciplined long-running coding work rather than unconstrained
> recursive multi-agent autonomy.

The design center for long-horizon support is the **primary Monitor
instance**. It owns the visible plan, user-facing continuity, delegation
decisions, result collation, and writer-of-record responsibilities. Sub-agents
support that long-horizon loop by performing bounded research and returning
results to the primary instance; they are not the main long-horizon surface
themselves.

## What “long-horizon” means here

In this codebase, long-horizon support is the combination of:

- **multi-step execution** across many tool calls,
- **plan persistence** across turns,
- **background delegated work** that can complete asynchronously,
- **resume behavior** after interruption or context switching,
- **bounded autonomy** with explicit limits and safety controls.

This is distinct from:

- single-turn tool use,
- purely synchronous request/response behavior,
- unconstrained autonomous swarms,
- world-state rollback or hermetic task isolation.

## Primary capabilities

### 1. Session-scoped planning with todo tools

Monitor has a first-class plan-tracking layer:

- `add_todo`
- `add_discovered_work`
- `list_todos`
- `update_todo`
- `delete_todo`
- `clear_todos`
- `get_task_context`
- `set_task_acceptance`
- `save_task_checkpoint`
- `record_task_scope_change`

Implementation:
- `src/monitor/lib/todo.py`
- `src/monitor/lib/todo_redis.py`

Key properties:
- todos are scoped to the current harness session,
- items have stable IDs,
- priorities are supported,
- status values support progress tracking,
- lightweight session-scoped acceptance criteria, scope-change notes, and
  resume checkpoints are supported,
- storage can use Redis with in-memory fallback,
- the system prompt explicitly instructs the model to use todos for non-trivial,
  multi-step work.

This is the core mechanism for long-horizon continuity across turns.

Recent additions on top of the original flat todo list:
- `add_discovered_work` adds newly discovered required work explicitly during
  feature implementation and can also record scope growth in the same step.
- `set_task_acceptance` lets feature completion be judged against explicit
  acceptance criteria instead of file edits alone.
- `save_task_checkpoint` and `get_task_context` provide lightweight
  session-scoped resume state for interrupted work.

### 2. Extended autonomous tool-use chains

`src/monitor/config.py` defines:

- `MAX_TOOL_CALL_DEPTH = 128`
- `MAX_REPEATED_TOOL_CALLS = 3`

The code comments explicitly frame this as sufficient headroom for substantial
coding workflows such as:

- multi-item plans,
- repeated view/edit/test loops,
- longer autonomous chains within a single user turn.

This matters because long-horizon coding is not only about multiple turns. It
also requires the system to sustain a non-trivial amount of sequential tool use
before stopping or asking the user to re-drive the session.

### 3. Sub-agent orchestration

Monitor includes a real orchestration stack for delegated tasks.

Key modules:
- `src/monitor/core/agent_tools.py`
- `src/monitor/lib/agent_orchestrator.py`
- `src/monitor/lib/agent_reporter.py`
- `src/monitor/lib/agent_protocol.py`
- `src/monitor/lib/agent_listener.py`
- `src/monitor/lib/screen_handler.py`

Capabilities:
- spawn sub-agents,
- list and inspect them,
- send follow-up prompts to persistent agents,
- gather results,
- kill agents,
- stream status and output back to the orchestrator.

Sub-agents are real Monitor instances launched in `--agent` mode inside
detached GNU screen sessions.

### 4. Async fire-and-continue behavior

The system is designed around **background delegation that does not freeze the
main session by default**.

The orchestration guidance in `src/monitor/lib/system_prompt.py` teaches:

- `agent_create(prompt)` returns immediately,
- the main orchestrator should keep helping the user,
- results may arrive asynchronously on a later turn,
- `agent_gather(...)` should be used only when blocking is truly necessary.

This is an important long-horizon property because it lets the orchestrator:

- continue mainline execution,
- avoid stalling the user session,
- interleave foreground work with delegated background work.

### 5. Result harvesting into later turns

The orchestration layer maintains pending injections so a completed sub-agent
can influence the orchestrator's next turn.

Implementation details include:
- `src/monitor/lib/agent_orchestrator.py` queues terminal notices,
- `src/monitor/core/conversation.py` folds those notices into
  `config.enqueue_next_llm_prefix(...)` on the main thread.

That means delegated work is not just visible to a human operator. It is also
fed back into the orchestrator's own future reasoning path.

### 6. Lifecycle controls for long-running delegated work

Sub-agent lifecycle support includes:

- one-shot agents by default,
- optional persistent agents,
- heartbeats,
- idle reaping,
- dirty disconnect detection,
- explicit kill support,
- caps on breadth and total spawned agents.

This reduces leakage and makes extended delegated execution operationally safer.

### 7. Delegated write controls

Long-horizon support includes an explicit delegated-write policy.

Relevant controls include:
- `SUBAGENT_WRITE_ACCESS = none | delegated | full`
- `MONITOR_SUBAGENT_WRITE_GRANTED=1` for explicit delegation,
- `MONITOR_SUBAGENT_WRITE_SCOPE` for scoped delegated writes.

Implementation surfaces:
- `src/monitor/core/tooling.py`
- `src/monitor/lib/screen_handler.py`
- `tests/monitor/core/test_subagent_write_access.py`

This is important because it means long-horizon support does **not** assume
that all delegated work is allowed to mutate the repo arbitrarily.

## Current architecture

### Orchestrator model

The current model is:

- one primary orchestrator session,
- zero or more bounded sub-agents,
- sub-agents report through a frame protocol,
- orchestrator remains the central coordinator.

This is not a peer swarm. It is a hierarchical, supervised model.

### Child transport and reporting

Sub-agents connect back to the orchestrator over an AF_UNIX socket and send
length-prefixed framed messages.

Frame types include:
- `hello`
- `status`
- `stdout`
- `result`
- `error`
- `exit`
- `heartbeat`
- `cancel`

The orchestrator records per-agent state and exposes terminal outcomes to
higher-level tools such as `agent_gather(...)`.

### UI bridge

The codebase also supports human-visible live feedback while agents run:

- toolbar status rendering,
- buffered output above the prompt,
- pending output draining,
- asynchronous completion notices.

Relevant code paths include:
- `src/monitor/core/conversation.py` via `_prompt_with_agent_bridge(...)`
- `src/monitor/tui/app.py` for TUI-mode draining

This makes long-horizon delegated work visible rather than opaque.

## Runtime constraints and safety defaults

A critical part of understanding long-horizon support is understanding what is
**deliberately constrained**.

### Orchestration is opt-in

By default:
- `MONITOR_ENABLE_AGENT_ORCHESTRATION = False`

So the system supports orchestration, but does not enable it automatically.

### Default spawn limits are intentionally conservative

Defaults in `src/monitor/config.py` include:

- `MONITOR_AGENT_MAX_DEPTH = 1`
- `MONITOR_AGENT_MAX_BREADTH = 1`
- `MONITOR_AGENT_MAX_TOTAL = 1`

Implications:
- no recursive multi-level orchestration by default,
- only one concurrent sub-agent by default,
- only one total sub-agent per session by default.

This is a strong signal that the architecture values safety and predictability
over raw autonomous throughput.

### Sub-agents are not meant to become an unconstrained swarm

The guidance in `system_prompt.py` explicitly says:

- delegate only independent, parallelizable work,
- do not delegate tightly coupled or trivial work,
- sub-agents do not decide ambiguous user intent,
- sub-agents cannot spawn their own sub-agents,
- the orchestrator remains the sole writer by default.

### Delegated writes are explicit and policy-bound

Sub-agent write behavior is controlled separately from orchestration enablement.
In practice:
- `none` blocks write tools in `--agent` mode,
- `delegated` requires explicit grant plus in-scope targets,
- `full` allows sub-agent writes without per-task delegation.

The current design still strongly prefers the orchestrator as the writer of
record, even though constrained delegated writing is supported.

## Practical operating guidance

### Recommended use cases

Monitor is currently a strong fit for:

- multi-step feature implementation,
- bug investigation followed by targeted edits,
- cross-file refactors with plan tracking,
- parallel audits across independent areas,
- background research while foreground implementation continues,
- follow-up review and testing loops across many steps.

### Poorer fit use cases

Monitor is a weaker fit for:

- unconstrained recursive agent trees,
- large swarms of simultaneous code-writing agents,
- unattended high-concurrency autonomous engineering at scale,
- workflows that require hard isolation and rollback of repo mutations.

### Recommended runtime profile

A practical bounded orchestration profile is:

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4` or `6`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `SUBAGENT_WRITE_ACCESS=none` or `delegated`

This preserves the current architectural intent while allowing useful
background delegation.

For practical setup and usage guidance, see
`docs/LONG_HORIZON_OPERATOR_GUIDE.md`.

### Planning guidance

For long-horizon work, the intended operating pattern is:

1. create a todo plan,
2. mark one item `in_progress`,
3. execute view/edit/test loops,
4. mark it `done`,
5. add newly discovered work explicitly rather than silently widening scope,
6. use sub-agents only for independent branches of investigation or drafting.

## What is already strong

### Strong areas

1. **Plan tracking exists and is integrated into the prompt contract**
2. **Long tool-call chains are explicitly supported**
3. **Async delegated work is real, not cosmetic**
4. **Failure states are surfaced honestly**
5. **Lifecycle controls are present**
6. **Delegation is bounded by policy and configuration**
7. **The orchestrator/worker split is architecturally clear**
8. **Delegated write policy fails closed by default**

These are the main reasons it is valid to describe the codebase as supporting
long-horizon coding.

## Known limitations and gaps

### 1. Planning is lightweight, not full workflow state

The todo system is useful, but it is still a lightweight plan list.
It does not appear to provide:

- dependency graphs between tasks,
- structured resumable execution checkpoints,
- artifact bundles per task,
- automatic replay or recovery of partially completed plans.

### 2. Concurrency is deliberately limited

The architecture supports delegation, but not broad fan-out by default.
This keeps the system safer, but it limits throughput for larger-scale
multi-agent exploration.

### 3. The orchestrator is still the main executor

This is a feature for safety, but a limit for autonomy.
The system is strongest when sub-agents act as:

- researchers,
- proposal generators,
- draft producers,
- bounded workers under explicit grants.

It is weaker as a free-form distributed code-writing platform.

### 4. No strong evidence yet of durable resumable checkpoints

If an extended task spans long periods or external interruptions, the system has
plan continuity, but not obviously a richer checkpoint and restart model for
exact execution state.

### 5. No first-class worktree isolation model

The docs and code acknowledge that conversation-history rollback is not
filesystem rollback. That means there is no true world-state undo for delegated
mutations.

### 6. Adjacent orchestration docs are complementary, not primary

The adjacent orchestration cache documents now focus more narrowly on the
sub-agent stack itself. This long-horizon document remains the broader,
top-level summary for planning, continuity, delegation, and bounded autonomy.

## Interpretation: what Monitor is today

Monitor should currently be understood as:

- **more than a chat assistant**,
- **more than a single-agent coding loop**,
- **less than a large-scale autonomous software engineering platform**.

A precise description is:

> Monitor is a long-horizon coding assistant with bounded agent orchestration,
> session-scoped planning memory, asynchronous delegated work, delegated-write
> policy controls, and strong operational guardrails.

## Improvement priorities

The most useful next improvements fall into three groups: quick wins,
medium-term architecture improvements, and the highest-value changes for
autonomous coding quality.

### Recently landed implementation track

Benchmarking is **not to be implemented at this time**. The first code-facing
long-horizon implementation track has now landed in three parts:

1. **Active background-work visibility**
   - active-agent visibility summaries are rendered for the primary
     orchestrator,
   - recent terminal outcomes are retained in compact form,
   - prompt responsiveness is preserved while that status remains visible.

2. **Persistent-agent follow-up hardening**
   - persistent lifecycle intent is recorded at spawn time,
   - `agent_send(...)` follow-ups are validated against one-shot, busy,
     errored, crashed, and idle-reaped sessions,
   - persistent-session metadata is stored explicitly.

3. **Initial resume and recovery semantics**
   - interrupted work now has lightweight session-scoped task context,
   - newly discovered required work can be added explicitly with
     `add_discovered_work`,
   - material scope growth and acceptance criteria can be recorded explicitly,
   - lightweight resume checkpoints can be stored and read back later.

This sequence improved operator trust first, then lifecycle correctness, then
interruption recovery. It builds directly on the current architecture without
requiring a richer task model or broader autonomy first.

These phases should be interpreted from the point of view of the **primary
Monitor instance**. The work is about making the orchestrator better at seeing,
collating, and resuming delegated work, not about turning sub-agents into
independent long-horizon actors.

For feature work specifically, this also means strengthening the primary
orchestrator's task discipline: plan before editing, expand the todo list when
required work is discovered, and close the task against acceptance criteria
instead of treating "files changed" as sufficient completion.

### Remaining near-term queue

The following code-facing items remain open after the initial implementation
track:

1. more operational validation of same-session resume behavior after user
   interruption,
2. clearer delegated-failure retry policy, if one is added at all,
3. stronger evidence that async completion notices remain concise under heavy
   concurrent usage,
4. richer task structure beyond a flat plan plus lightweight task context.

### Quick wins

These are relatively low-risk changes that improve usability, trust, and the
practical effectiveness of the existing architecture.

1. **Add a practical operator guide**
   - document recommended orchestration settings,
   - explain when to use todos,
   - explain when to delegate,
   - explain when to keep work inline.

2. **Do not implement long-horizon benchmark tasks at this time**
   - multi-file bugfix workflows,
   - investigate-then-fix workflows,
   - background audit plus foreground implementation,
   - partial-failure and resume scenarios.

   This is supporting validation work and is explicitly out of scope for the
   current long-horizon implementation track.

3. **Tighten async completion summaries**
   - make injected completion notices concise,
   - avoid polluting later turns with overly long background summaries.

4. **Document failure-handling patterns**
   - what the orchestrator should do when an agent is refused by caps,
   - what to do when an agent times out,
   - what to do after dirty disconnects,
   - what to do after partial success.

5. **Make researcher-vs-worker mode explicit in docs**
   - the architecture already leans this way,
   - the workflow should be documented clearly for contributors and operators.

6. **Improve active-work visibility**
   - add or document summary views for active agents,
   - make pending and completed delegated work easier to inspect,
   - improve trust during long-running sessions.

7. **Add more persistent-agent workflow tests**
   - cover `agent_create(..., persistent=True)`,
   - cover `agent_send(...)`,
   - cover `agent_kill(...)` lifecycle expectations.

### Medium-term architecture improvements

These changes would materially improve resilience and the system's ability to
handle more ambitious long-horizon work.

1. **Durable execution checkpoints**
   - persist more than a flat todo list,
   - track current step, delegated subtasks, blockers, and verification state,
   - make interrupted work easier to resume.

2. **Richer task model beyond flat todos**
   - optional dependencies,
   - blocked and waiting states,
   - grouped phases or task clusters,
   - clearer modeling of investigation, implementation, and verification.

3. **Structured artifact passing from sub-agents**
   - allow delegated tasks to return not just prose summaries but also:
     - candidate diffs,
     - file targets,
     - suggested tests,
     - risk markers,
     - confidence signals.

4. **Retry and resume semantics for delegated work**
   - formalize how failed delegated tasks are retried,
   - distinguish retry-in-place from retry-with-narrowed-scope,
   - improve recovery after partial delegated failure.

5. **Project-scoped durable memory**
   - separate session task memory from longer-lived project knowledge,
   - preserve architectural decisions, conventions, and known gotchas.

6. **Stronger delegated-write observability**
   - improve operator visibility into delegated mutation authority,
   - make grant and scope decisions easier to inspect.

7. **Better observability surfaces**
   - summarize active agent status,
   - show time since last heartbeat,
   - surface recent completions and failures,
   - make long-running sessions easier to understand.

8. **Delegated cost accounting**
   - aggregate child costs into orchestrator-level reporting,
   - make broader fan-out safer to operate.

9. **Per-task long-horizon benchmarking**
   - track pass rates and common failure patterns across representative coding
     tasks,
   - use real workload data to guide future autonomy changes.

### Highest-value changes for autonomous coding quality

If the goal is specifically to improve autonomous coding quality rather than
just general orchestration, the highest-value changes are:

1. **Durable checkpoints and resume semantics**
   - the single biggest reliability improvement for long-running coding tasks,
   - reduces wasted effort after interruption or partial completion.

2. **Structured sub-agent result artifacts**
   - improves aggregation quality,
   - reduces context-window waste,
   - makes delegated results easier to act on programmatically.

3. **Project-scoped durable memory**
   - reduces repeated rediscovery,
   - improves consistency with repository conventions,
   - strengthens multi-session coding quality.

4. **Richer plan and task structure**
   - supports larger features and investigations more reliably,
   - reduces the risk of dropped subproblems or poor sequencing.

5. **Stronger delegated execution boundaries**
   - keeps ambitious autonomous behavior safe,
   - preserves clear accountability for code changes.

6. **Worktree or sandbox isolation for write-capable sub-agents**
   - important if the system ever expands from researcher-style delegation to
     more parallel code-writing workflows,
   - reduces write-conflict and contamination risk.

7. **A dedicated long-horizon benchmark suite**
   - essential for validating improvements,
   - turns architecture changes into measurable progress.

## File references

Core files relevant to this topic:

- `src/monitor/config.py`
- `src/monitor/app.py`
- `src/monitor/core/agent_tools.py`
- `src/monitor/core/conversation.py`
- `src/monitor/core/tooling.py`
- `src/monitor/lib/agent_orchestrator.py`
- `src/monitor/lib/agent_reporter.py`
- `src/monitor/lib/agent_protocol.py`
- `src/monitor/lib/agent_listener.py`
- `src/monitor/lib/screen_handler.py`
- `src/monitor/lib/system_prompt.py`
- `src/monitor/lib/todo.py`
- `src/monitor/lib/todo_redis.py`

Related cache docs:

- `docs/cache/PLAN_AGENT_ORCHESTRATION.md`
- `docs/cache/ROADMAP_AGENT_ORCHESTRATION.md`
- `docs/cache/CHECKLIST_AGENT_ORCHESTRATION.md`

## Bottom line

Monitor already supports meaningful long-horizon coding and agentic work.

It is strongest when used as:
- a disciplined multi-step coding orchestrator,
- a bounded delegator of independent background tasks,
- a system that tracks plans explicitly and applies final changes centrally.

It is not yet optimized for unconstrained, high-scale, recursive autonomous
software engineering, but that is also clearly not the design center of the
current architecture.
