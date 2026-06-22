# Long-Horizon Operator Guide

Practical setup and operating guidance for Monitor's bounded long-horizon and
sub-agent orchestration capabilities.

This guide is for people who want to use the current codebase effectively and
safely. It focuses on runtime behavior that already exists today:

- explicit planning with todo tools,
- lightweight task context for acceptance criteria and resume checkpoints,
- bounded background sub-agent orchestration,
- one-shot and persistent agent lifecycles,
- delegated-write controls,
- async fire-and-continue operation.

For broader architectural context, see:
- `docs/cache/SPEC_LONG_HORIZON.md`
- `docs/cache/PLAN_LONG_HORIZON.md`
- `docs/cache/PLAN_AGENT_ORCHESTRATION.md`

## What this guide is for

Use this guide when you want to:
- enable orchestration safely,
- choose sensible caps,
- understand when to delegate versus work inline,
- understand one-shot versus persistent agents,
- understand delegated-write modes,
- handle common failure modes without overreacting.

## Mental model

Monitor's current long-horizon behavior is best understood as:

- one primary orchestrator,
- optional bounded background sub-agents,
- explicit visible planning,
- async result harvest into later turns,
- conservative defaults.

The long-horizon feature primarily applies to the **primary Monitor
instance**. That main session owns the plan, decides when to delegate,
collates sub-agent results, and remains the writer of record. Sub-agents are
normally bounded research workers feeding that primary session.

This is **not** an unconstrained autonomous engineering swarm.

The intended default operating style is:
1. create a visible task plan,
2. execute one step at a time,
3. delegate only genuinely independent background work,
4. keep the orchestrator as the writer of record whenever possible,
5. treat delegated writes as exceptional.

## Enabling orchestration

The master switch is:

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`

Without that enabled, `agent_create(...)` and related orchestration behaviors
remain unavailable.

Useful related controls:
- `MONITOR_AGENT_MAX_DEPTH`
- `MONITOR_AGENT_MAX_BREADTH`
- `MONITOR_AGENT_MAX_TOTAL`
- `MONITOR_AGENT_HEARTBEAT_TIMEOUT`
- `MONITOR_AGENT_IDLE_TIMEOUT`
- `SUBAGENT_WRITE_ACCESS`

## Conservative defaults

The codebase defaults are intentionally conservative:

- `MONITOR_ENABLE_AGENT_ORCHESTRATION = False`
- `MONITOR_AGENT_MAX_DEPTH = 1`
- `MONITOR_AGENT_MAX_BREADTH = 1`
- `MONITOR_AGENT_MAX_TOTAL = 1`
- `SUBAGENT_WRITE_ACCESS = none`

These defaults mean:
- orchestration is opt-in,
- only one sub-agent can run at once by default,
- only one total sub-agent can be spawned per session by default,
- recursive multi-level orchestration is blocked by default,
- sub-agents cannot write by default.

This is deliberate. Raise the limits only after you trust the workflow you are
running.

## Recommended operating profiles

### Profile A: safest first use
Use this when first enabling orchestration.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=1`
- `MONITOR_AGENT_MAX_TOTAL=1`
- `SUBAGENT_WRITE_ACCESS=none`

Use cases:
- trying orchestration for the first time,
- simple background research,
- one audit thread while the orchestrator keeps working.

### Profile B: practical bounded background work
Use this when orchestration is already behaving well.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4` or `6`
- `SUBAGENT_WRITE_ACCESS=none` or `delegated`

Use cases:
- parallel audits across independent surfaces,
- background investigation while foreground implementation continues,
- multi-branch read-heavy exploration.

This is the recommended bounded profile for real work.

### Profile C: write-capable delegated work
Use this only when you explicitly want sub-agents to mutate files.

- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=1` or `2`
- `MONITOR_AGENT_MAX_TOTAL=2` to `4`
- `SUBAGENT_WRITE_ACCESS=delegated`

Prefer `delegated` over `full` whenever possible.

Use cases:
- narrow, explicit delegated edits,
- highly scoped worker tasks with clear file targets.

## When to use todos

For long-horizon work, the default pattern should be:
- create a todo plan,
- set acceptance criteria for feature work,
- mark one item `in_progress`,
- execute,
- verify,
- mark it `done`,
- add newly discovered work explicitly with `add_discovered_work`,
- leave a checkpoint if the task may pause or resume later.

Use todos for:
- multi-step changes,
- multi-file edits,
- read-then-edit workflows,
- work that may span turns,
- work that includes verification and follow-up.

Skip todos only for:
- pure Q&A,
- a genuinely trivial one-shot action,
- a single isolated tool call with no surrounding workflow.

### Task-context tools

The current codebase also supports lightweight session-scoped task context:

- `set_task_acceptance` for feature-level acceptance criteria,
- `add_discovered_work` for newly uncovered required work,
- `save_task_checkpoint` for a compact resume marker,
- `get_task_context` to read that state back later.

Use these as the extension of the todo plan rather than overloading todo
`notes` as a progress log.

## When to delegate versus work inline

### Delegate when the work is:
- independent,
- parallelizable,
- mainly investigative,
- likely to save user wait time,
- likely to preserve orchestrator focus.

Good examples:
- audit one subsystem while you edit another,
- compare two independent hypotheses,
- inventory several independent files or surfaces,
- research implementation options in the background.

### Do it inline when the work is:
- tightly coupled,
- sequential,
- narrow enough that the orchestrator can just do it,
- mostly editing in one place,
- dependent on rapid local decisions.

Good examples:
- a one-file bugfix,
- a read/edit/test loop on the same surface,
- a small refactor requiring tight local feedback.

### Do not delegate when:
- user intent is ambiguous,
- architecture or behavior tradeoffs are unresolved,
- the task is trivial,
- the task is mostly orchestrator writing work rather than background research.

## One-shot versus persistent agents

### One-shot agents
One-shot is the default.

Use one-shot when the sub-agent should:
- do one focused task,
- report a result,
- exit immediately.

This is the preferred default because it:
- avoids lingering processes,
- keeps lifecycle simple,
- fits the researcher pattern well.

### Persistent agents
Use persistent agents only when you expect follow-up prompts to the same child.

Use persistent when the sub-agent should:
- remain alive for additional questions,
- continue a specific line of work across follow-ups,
- preserve child-local context for that line of work.

Persistent agents are more expensive operationally because they require:
- explicit cleanup,
- clearer tracking,
- more discipline around follow-up usage.

Current follow-up rules are intentionally strict:
- `agent_send(...)` is only for persistent agents,
- one-shot sessions reject follow-up sends,
- busy sessions reject follow-up sends until they finish,
- crashed, errored, or idle-reaped sessions reject follow-up sends.

### Practical rule
Default to one-shot.
Choose persistent only when you already know you will send follow-ups to the
same sub-agent.

## When to use `agent_gather(...)`

`agent_gather(...)` is the explicit blocking wait path.

Use it only when you truly cannot proceed without the delegated result right
now.

Good uses:
- you need all delegated findings before making a decision,
- the current foreground turn cannot continue meaningfully,
- you are intentionally synchronizing parallel research before synthesis.

Avoid it when:
- the orchestrator can continue useful work,
- the delegated task is background investigation,
- the user would benefit more from continued foreground progress.

Practical rule:
- prefer fire-and-continue,
- use gather only for genuine synchronization points.

## Delegated-write modes

Sub-agent write behavior is controlled by `SUBAGENT_WRITE_ACCESS`.

### `SUBAGENT_WRITE_ACCESS=none`
This is the safest default.

Behavior:
- sub-agents cannot use write-capable tools,
- delegated work is effectively research/proposal only.

Use when:
- you want background investigation only,
- you are early in adoption,
- you want the orchestrator to remain the sole writer.

### `SUBAGENT_WRITE_ACCESS=delegated`
This allows writes only when explicitly granted for the task.

Behavior:
- a sub-agent still cannot write unless explicit delegation metadata is passed,
- delegated writes can be limited by path scope.

Use when:
- you want narrow worker behavior,
- you want some delegated edits but still need strong boundaries,
- you want to preserve accountability.

This is the preferred mode when delegated writes are necessary.

### `SUBAGENT_WRITE_ACCESS=full`
This allows write-capable sub-agents without per-task delegated grant checks.

Use sparingly.

Use when:
- you fully trust the workflow,
- you intentionally want write-capable sub-agents as a normal operating mode,
- you accept the increased risk and coordination burden.

For most users, `full` should not be the default profile.

## Failure handling playbook

### Agent creation is refused by caps
Meaning:
- breadth or total cap has been reached.

What to do:
- continue non-blocked foreground work,
- wait for current work to finish,
- gather only if needed,
- raise caps only deliberately.

Do not immediately widen caps unless you actually need the extra concurrency.

### Agent times out or remains pending
Meaning:
- the delegated task has not reached terminal state within the wait window.

What to do:
- treat it as pending, not success,
- continue non-blocked work,
- retry or re-scope only when the result is genuinely needed.

### Dirty disconnect or heartbeat lapse
Meaning:
- the child likely crashed or stopped responding.

What to do:
- treat it as failure,
- preserve successful results from other delegated tasks,
- re-run only the failed branch if still needed,
- do not assume repo rollback.

### Partial success across multiple agents
Meaning:
- some delegated tasks succeeded, others failed or are pending.

What to do:
- use the successful findings,
- keep failure handling local to the failed branch,
- avoid throwing away good work because one branch failed.

## Practical usage patterns

### Pattern 1: background audit plus foreground implementation
- create a todo plan,
- spawn one background researcher for an independent audit,
- continue implementing in the orchestrator,
- incorporate the result when it arrives later.

This is the canonical fire-and-continue workflow.

### Pattern 2: bounded parallel investigation
- split a problem into independent surfaces,
- spawn one researcher per surface,
- continue lightweight foreground work,
- gather only at the point where synthesis is truly needed.

### Pattern 3: tightly scoped delegated worker
- keep orchestration enabled,
- use `SUBAGENT_WRITE_ACCESS=delegated`,
- constrain delegated scope,
- use the orchestrator as reviewer and integrator.

This should remain exceptional rather than default.

## Recommended habits

- keep `MONITOR_AGENT_MAX_DEPTH=1` unless you have a very strong reason not to,
- keep breadth low until you trust the workflow,
- prefer one-shot over persistent,
- prefer `none` or `delegated` over `full`,
- treat delegated writes as exceptional,
- use todos as visible working memory,
- prefer continued foreground progress over unnecessary blocking gathers.

## What this guide does not promise

This guide does not imply:
- unconstrained autonomous engineering,
- filesystem rollback after delegated failure,
- strong durable resumable checkpoints,
- broad parallel code-writing safety.

What does exist today is lighter-weight:
- session-scoped resume checkpoints,
- acceptance criteria,
- explicit discovered-work capture,
- explicit scope-growth notes.

Those remain later-stage improvements rather than baseline guarantees.

## Bottom line

The current codebase already supports meaningful long-horizon operation.

Use it best by:
- planning explicitly,
- enabling orchestration deliberately,
- keeping delegation bounded,
- preferring one-shot researchers,
- treating delegated writes as exceptional,
- blocking only when synchronization is truly necessary.
