# Roadmap: Agent Orchestration (src/monitor/)

Phased delivery plan derived from `PLAN_AGENT_ORCHESTRATION.md` and
`CHECKLIST_AGENT_ORCHESTRATION.md`. Each phase ends at a demonstrable,
shippable state. Phases are sequential; later phases assume earlier ones land.

> **Starting point.** A subagent = an instance of the app in `--agent` mode.
> The spawn machinery already exists: `:agent create` launches `python -m
> monitor` in a screen session with depth propagation, a per-session
> `<name>.sock`, a poller, and prompt injection. prompt_toolkit is already the
> input layer. So this roadmap starts from a substantial base — the early
> phases are "flip on + assemble," not greenfield.

---

## Phase 0 — Foundations (config + decisions)  — *mostly already done*
**Goal:** Lock the invariants before any wire code.
- [done] Config plumbing + depth propagation + per-session socket path exist.
- Decide socket dir/naming and confirm UNIX-only stance.
**Exit criteria:** Documented decisions; config verified as single source of truth.
**Risk:** Low.

## Phase 0.5 — Wire `:agent create` to launch a real `--agent` subagent
**Goal:** The spawned child actually runs in agent mode and reports back.
- Add `--agent` to `monitor_cmd` (`screen_handler.py:75`).
- Pass `MONITOR_AGENT_SOCKET=<name>.sock` in the spawn `env` (`:364`).
- Build the `config.AGENT` startup reporting path (`app.py:354`): connect +
  emit `hello`/`status`/`stdout`/`result`, reusing the client at `:667`.
**Exit criteria:** A spawned subagent connects to its socket and emits frames an
ad-hoc listener can read.
**Risk:** Medium. The child-side reporting path is the main net-new code, but
it's localized and reuses existing idioms.

## Phase 1 — Protocol library (no UI)
**Goal:** A standalone, tested frame (de)serializer.
- Length-prefixed framing, envelope, versioning, oversize rejection.
- Partial-read reassembly.
- Shared by both roles (orchestrator + `--agent` child).
**Exit criteria:** Round-trip + partial-read tests green.
**Risk:** Low. Pure logic, easy to test in isolation.

## Phase 2 — Transport (sockets, headless)
**Goal:** Orchestrator can accept connections and receive frames with no UI.
- AF_UNIX listener, perms, stale-socket cleanup, teardown.
- Accept thread + reader threads that log frames (no bridge yet).
- A throwaway test client emitting `hello`/`status`/`exit`.
**Exit criteria:** Frames from a test client appear in logs; clean shutdown
unlinks the socket.
**Risk:** Medium. Socket lifecycle + cleanup are the fiddly parts.

## Phase 3 — Bridge & state ownership (blocking-`.prompt()` model)
**Goal:** Frames flow safely into lock-guarded shared state.
- Reader threads → lock-guarded status map + bounded pending-output queue.
- Single lock over status map + pending-output queue + connection list.
- Backpressure + status coalescing; frames between prompts buffer and flush.
- NOTE: no `asyncio.Queue`/`call_soon_threadsafe` — `get_input` uses blocking
  `session.prompt()` (`conversation.py:473`), so there is no loop to schedule on.
**Exit criteria:** Concurrent multi-agent frame storm with zero shared-state
races; `result`/`error`/`exit` never dropped under load.
**Risk:** High. This is the correctness crux — concurrency.

## Phase 4 — Terminal UI
**Goal:** Live status without display corruption.
- `bottom_toolbar` reads the status map; `get_app().invalidate()` (guarded).
- `run_in_terminal`/`patch_stdout` for blocks; wrap `session.prompt()` in
  `patch_stdout()`.
- Verify prompt input buffer is never touched by a reader thread.
**Exit criteria:** Type at the prompt while agents stream output; no cursor
corruption, toolbar updates live.
**Risk:** Medium. prompt_toolkit is already in use, so this is additive.

## Phase 5 — Lifecycle, failure & rollback
**Goal:** Crash semantics are correct and honest.
- Clean vs dirty disconnect; heartbeat timeout.
- Wire dirty disconnect → conversation-history rollback.
- UI/docs state rollback scope (history, not filesystem).
**Exit criteria:** Killing an agent mid-run triggers history rollback; clean
exit does not. Scope messaging is explicit.
**Risk:** High. Touches existing history-rollback mechanism.

## Phase 6 — Index, depth & nesting
**Goal:** Safe targeting and bounded recursion.
- Stable `agent_id` registry; index resolved at parse time.
- Depth propagation via env; ceiling enforced at `hello`.
- Direct-children-only toolbar.
**Exit criteria:** Kill cannot re-point a stale index; depth ceiling blocks
over-deep spawns.
**Risk:** Medium.

## Phase 7 — Hardening & compatibility
**Goal:** Production-readiness without regressions.
- Confirm screen PTY (`attach`) + logfiles (`logs`/`logfile`) intact.
- Legacy `stuff` path remains as non-participating tier.
- Confirm synchronous backend unchanged.
- Full test matrix from the checklist §10.
**Exit criteria:** All checklist items checked; no async creep into core;
existing `:agent` subcommands unaffected.
**Risk:** Medium.

## Phase 8 — LLM orchestration layer (the capstone)
**Goal:** Turn the subsystem from "spawns processes" into "an LLM that
orchestrates subagents, aggregates their findings, and acts." This is where the
existing LLM-callable tools (`tool_definitions.py:~682-749`) become genuinely
useful and the system prompt teaches the model to use them.

The crux this phase solves: a subagent runs **asynchronously**, but an LLM turn
is strictly request→response. Phases 1–7 surface subagent output to the *human
terminal*; this phase routes findings back into the *orchestrator LLM's token
context* as tool results — a distinct channel that does not otherwise exist.

### 8a. Result-return-into-context channel (the keystone)
- Add a **blocking gather tool** rather than relying on the LLM to poll
  (nothing re-invokes the LLM when a subagent finishes, so polling busy-waits):
  - `agent_create(prompt) → agent_id` returns immediately (fire).
  - LLM fires N.
  - `agent_gather([ids], timeout) → structured results` blocks until all report
    (or quorum/timeout), returning the `result`-frame payloads as ONE tool result.
- Note: `agent_logfile` returns a *path*, not content — add a result-retrieval
  tool that returns `result`-frame payloads directly for LLM consumption.

### 8b. Structured summaries (context-budget protection)
- Subagents return concise structured findings via the `result` frame `summary`
  field — never raw transcripts (those blow the orchestrator's context window).
- Bake into the `--agent`-mode subagent system prompt: "your final `result` is
  data for an orchestrator; return a tight, structured summary."
- Aggregation happens over summaries.

### 8c. Breadth & cost caps (not just depth)
- `MONITOR_AGENT_MAX_DEPTH` caps recursion depth only; add a **sibling/breadth
  cap** and a **total-agent / token budget**.
- Aggregate child token-costs up to the orchestrator (extend existing cost
  trackers to sum children). Prevents "create subagents as necessary" from
  becoming a cost incident.

### 8d. Partial-failure honesty
- `agent_gather` must report partial outcomes explicitly — e.g. "4 of 5
  succeeded; agent-3 crashed (dirty disconnect)". NEVER silently drop a failed
  subagent; the LLM can only act correctly if it knows what's missing.
- Ties into Phase 5: a crashed child's history rollback is local to that child;
  the orchestrator still receives a structured "missing/failed" entry.

### 8e. Orchestrator as sole file writer (conflict prevention)
- **Researcher subagents** = read-only; safe to fan out wide (the sweet spot).
- **Worker subagents** = write-capable; default policy is they do NOT write the
  working tree directly. The **primary orchestrator is the single writer of
  record** — subagents return proposed changes/findings, the orchestrator
  applies them serially. This sidesteps concurrent-write conflicts entirely.
- Only if/when parallel writers are truly needed do we revisit per-agent
  worktree isolation (still out of scope below).

### 8f. Follow-up prompts & subagent lifecycle
- `agent_send` makes subagents stateful, conversational sessions (they are full
  monitor instances with history).
- Define **queue-vs-interrupt** semantics for a follow-up sent while a subagent
  is mid-task, and an **idle-reaping** policy so subagents don't pile up.

### 8g. System-prompt orchestration guidance
- Replace open-ended "create subagents as necessary" with explicit
  **when-to-fan-out** criteria: independent parallelizable subtasks, broad
  search, or isolation needed — vs. do-it-inline otherwise.
- Make the model cost/latency-aware; crisp tool descriptions; recommend the
  spawn-N-then-gather pattern.

**Exit criteria:** The orchestrator LLM can fan out N researcher subagents from
a single user request, receive structured summaries back in-context via
`agent_gather` (with any failures surfaced), aggregate them, and act — applying
all file writes itself. Breadth/cost caps enforced; follow-ups work.
**Risk:** Medium-High. 8a (result channel) and 8e (sole-writer policy) are the
load-bearing pieces; 8c/8d are about not letting it run away or lie.

---

## Dependency graph
```
P0 ─► P0.5 ─► P1 ─► P2 ─► P3 ─► P4 ─► P5 ─► P6 ─► P7 ─► P8
       │                    │                   ▲          │
       │                    └── state model ────┘          │
       │                        (P3 lock-guarded state      │
       │                         underpins P5/P6)            │
       │                                                     │
       └── --agent reporting path is the keystone;   P8 reuses that SAME
           nothing downstream is observable until     channel, but routes
           the child actually emits frames.           results into the LLM's
                                                       context (tool results),
                                                       not just the terminal.
```
P8 is the capstone: P0.5–P7 make subagents *observable to the human*; P8 makes
them *usable by the orchestrator LLM*.

## Highest-risk items (watch these)
1. **Phase 8a result channel** — getting async subagent findings back into the
   synchronous LLM turn as tool results (the gather tool). Without it, "the LLM
   orchestrates" does not happen.
2. **Phase 5 rollback scope** — must stay honest: conversation-history only,
   NOT filesystem side effects. Touches the existing history mechanism.
3. **Phase 8e sole-writer policy** — keeps "aggregate and act" from corrupting
   the working tree; the cheap alternative to per-agent worktree isolation.
4. **Phase 3 bridge** — blocking `.prompt()` means lock-guarded shared state;
   any reader thread that prints directly or mutates outside the lock is a
   latent display/state race.
5. **Phase 0.5 child reporting path** — the keystone net-new code; everything
   downstream is unobservable until it works.
6. **Phase 2 socket cleanup** — stale sockets / orphaned children on crash.

## Out of scope (explicitly deferred)
- True side-effect / filesystem rollback (would need per-agent worktree
  isolation). NOTE: Phase 8e's sole-writer policy is the deliberate, cheaper
  alternative — parallel write-workers + worktree isolation stay deferred until
  genuinely needed.
- Windows support (AF_UNIX + screen are UNIX-only here).
- Porting orchestration into `src/monitor_oop/`.
