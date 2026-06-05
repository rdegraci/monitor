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
**Goal:** Live status + live background output without display corruption.
- `bottom_toolbar` reads the status map; `get_app().invalidate()` (guarded). DONE.
- `patch_stdout()` wraps the prompt; output flushes between prompts. DONE.
- **live-flush-during-prompt** (RE-ELEVATED — required by the async model): a
  background flusher streams agent `stdout`/`result` above the live prompt via
  `run_in_terminal`, with **coalescing/verbosity caps** so a chatty agent
  doesn't spam the input line. (Was deferred under the blocking-gather
  assumption; now in scope because the human keeps working while agents run.)
- Verify prompt input buffer is never touched by a reader thread.
**Exit criteria:** Type at the prompt while a background agent streams output
above it; no cursor corruption; toolbar updates live.
**Risk:** Medium. Additive (prompt_toolkit already in use); the live-flush
thread→app bridge is the fiddly part.

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
is request→response. The UX decision (2026-06-04) is **async fire-and-continue**
— spawning returns instantly, the human keeps working, and results flow back
later. A blocking gather is explicitly NOT the default (it freezes the REPL).

### 8a. Async result harvest (the keystone)
- `agent_create(prompt) → agent_id` **fires and returns immediately; the turn
  ENDS.** The human is back at a live prompt; the subagent runs in the
  background.
- On a terminal `result`/`error` frame, the orchestrator **injects the result
  into the LLM's NEXT turn** via `config.enqueue_next_llm_prefix(...)`
  (`[background agent <id> finished: <summary>]`), deduped/delivered-once — so
  completed work reaches the model on the human's next message, no blocking.
- (Optional) a **non-blocking** `agent_poll(ids?)` tool returns whatever is
  terminal-so-far on demand; never waits.
- `agent_gather([ids], timeout)` — already built — is **demoted to an explicit
  "wait for these now" escape hatch**, not the default path.
- Note: `agent_logfile` returns a *path*; the harvest/poll return `result`-frame
  payloads directly.

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
- Both harvest paths surface failures. The **async injection** says
  `[background agent <id> FAILED: <reason>]`; `agent_poll`/`agent_gather` bucket
  every requested id as `ok` / `failed` / `pending`. NEVER silently drop a
  crashed subagent.
- A crash is detected via dirty disconnect OR heartbeat-lapse (Phase 5), so even
  a hung agent eventually surfaces as failed rather than waited-on forever.

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
- Teach the **fire-and-continue** pattern: spawn a researcher and CONTINUE the
  conversation; its result arrives automatically on a later turn. Do NOT block
  on `agent_gather` unless you genuinely cannot proceed without the result.
- Make the model cost/latency-aware; crisp tool descriptions; remain sole writer.

### 8h. Live-flush human UI (re-elevated — see Phase 4)
- Because the human now keeps working while agents run in the background,
  **live-flush-during-prompt** (stream agent output above the prompt via
  `run_in_terminal`, with coalescing for chatty agents) moves from deferred to
  IN SCOPE — it's how the human sees background progress without blocking.

**Exit criteria:** From one request the orchestrator can spawn a background
researcher and the turn **ends immediately**; the human keeps instructing the
orchestrator while it runs; the agent's result streams to the human live AND is
injected into the orchestrator's next turn (failures surfaced); the orchestrator
aggregates and acts as sole writer. Caps enforced. `agent_gather` works as the
explicit-wait escape hatch.
**Risk:** Medium-High. 8a (async harvest) and 8e (sole-writer) are load-bearing;
8c/8d keep it from running away or lying.

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
1. **Phase 8a async harvest** — injecting completed/failed background results
   into the LLM's *next* turn (via `enqueue_next_llm_prefix`), deduped, without
   blocking. This is what makes fire-and-continue real; blocking gather is the
   demoted escape hatch.
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
