# Design Note: Sub-agent Frame Protocol & Terminal Bridge

> Scope: `src/monitor/` only. This is a design spec, not implemented code.
> It pins down the two riskiest pieces of the agent-orchestration plan —
> the wire protocol and the thread→event-loop bridge — plus the
> state-ownership rule that keeps both race-free.

## What a subagent is

**A subagent is an instance of the monitor app itself, launched in `--agent`
mode** (the `--agent` CLI flag, which sets `config.AGENT = True` —
`app.py:272`, `app.py:354`). Orchestration = a parent monitor process spawns
`monitor --agent` children (inside detached GNU screen sessions) that dial back
to the orchestrator over an AF_UNIX socket. Because subagents share the entire
codebase, they can be taught the frame protocol below by reusing existing code
— the orchestrator and the subagent are the same program in two roles. This is
what makes orchestration *real* rather than cosmetic log-scraping.

## Background

Agent orchestration already exists in partial form in `src/monitor/`:

- `agent_create` / `agent_send` / `agent_list` / `agent_logfile` / `agent_kill`
  are LLM-callable tools (`src/monitor/core/agent_tools.py`, exposed via
  `src/monitor/lib/tool_definitions.py` — schemas at `~682-749`).
- Sub-agents are detached **GNU screen** sessions. `spawn.py` already calls
  `create_interactive_subagent`, which returns a **`status_socket`**, and
  `_start_orchestrator_poller` already spins up an `OrchestratorPoller` +
  `queue.Queue` + background thread (`spawn.py:120-206`).
- The orchestrator registry registers each session under **multiple keys**
  (`session_name`, `token`, `screen_token`, `screen`) — `spawn.py:190`.

### What `:agent create` already does (and the two gaps)

`:agent create <prompt>` → `agent_create(prompt)` →
`ScreenHandler.create_interactive_subagent(prompt)`. This path is ~90% wired
toward the intended behavior:

- Launches a real app instance via
  `screen -S <name> -dm env MONITOR_AGENT_DEPTH=<curr+1> [MONITOR_AGENT_MAX_DEPTH=…] python -m monitor`
  (`screen_handler.py:364`). ✅
- Propagates and ceiling-checks depth. ✅
- Creates a per-session socket path `<name>.sock`. ✅
- Starts an `OrchestratorPoller`. ✅
- Injects the prompt after waiting for `"Monitor ready!"`, then `stuff`s it in. ✅

**Two concrete gaps remain — this is the actual net-new work:**

1. **Spawn side:** `self.monitor_cmd` defaults to `["python", "-m", "monitor"]`
   (`screen_handler.py:75`) — it does **not** include `--agent`, so the child
   currently runs as a normal interactive monitor, not an agent-mode instance.
   Fix: add `--agent` to the command, and hand the child its socket path (e.g.
   `MONITOR_AGENT_SOCKET=<name>.sock` in the same `env` list that already
   carries the depth vars).
2. **Child side:** `--agent` is currently a near-noop — `app.py:354` only sets
   `config.AGENT=True` and logs. The **reporting client** (connect to the
   socket, emit framed `status`/`stdout`/`result` frames) still needs to be
   built into the `config.AGENT` startup path. It can reuse the existing
   AF_UNIX client idiom at `screen_handler.py:667`.

Gating (config, not CLI flags — `src/monitor/config.py`):

- `MONITOR_ENABLE_AGENT_ORCHESTRATION` (default `False`) — master switch;
  gates `agent_create` and `agent_send` only.
- `MONITOR_AGENT_DEPTH` (default `0`) — current recursion depth.
- `MONITOR_AGENT_MAX_DEPTH` (default `1`) — depth ceiling.

So the architecture below is largely a matter of *committing* to a direction
the code is already crawling toward.

## Architectural decision: screen + AF_UNIX hybrid

Keep **screen** as the process/PTY substrate (free detach/attach, logfiles,
survival across orchestrator restarts) and use **AF_UNIX** as the structured
control/status channel. A sub-agent that participates in orchestration must be
a *cooperative* process that dials back on the socket and speaks the frame
protocol below. The legacy `screen -dm` + `-X stuff` path (`spawn.py:135-145`)
is fire-and-forget and cannot participate — that's an acceptable second tier.

Two framings from the plan are corrected here and must stay corrected in code
and UI:

1. **"Transaction security" is conversation-history rollback, not world
   rollback.** Process isolation gives independent memory scopes, but
   sub-agents run file tools that mutate the filesystem; killing a crashed
   agent does not undo committed side effects.
2. **Failure detection is socket-disconnect, not POSIX exit code.** A
   screen-detached child is reparented; you cannot reliably `waitpid` it.

---

## Part 1 — Frame Protocol

### Transport
- **AF_UNIX, `SOCK_STREAM`**, one socket file per orchestrator (the listener),
  short path (mind the ~104-byte `sun_path` limit — e.g.
  `$XDG_RUNTIME_DIR/m3-<pid>.sock`, not deep in appdir).
- Perms: socket dir `0700`, socket `0600`. Optionally verify peer uid via
  `SO_PEERCRED` (Linux) / `LOCAL_PEERCRED` (macOS) on accept.
- Direction is **asymmetric**: child→orchestrator carries status/output/result;
  orchestrator→child carries only control (cancel/shutdown).

### Framing (the part SOCK_STREAM forces on you)
Stream sockets do not preserve message boundaries, so every frame is:

```
┌────────────┬───────────────────────────┐
│ uint32 BE  │  JSON body (length bytes)  │   ← length-prefixed
│  length    │                            │
└────────────┴───────────────────────────┘
```

4-byte big-endian length prefix + UTF-8 JSON body. Length-prefix beats
newline-delimited because agent output legitimately contains newlines. Cap a
frame at ~1 MiB; reject oversize as a protocol error (prevents a runaway child
OOM-ing the orchestrator).

### Envelope
Every frame body shares one envelope so the reader can dispatch before caring
about type:

```json
{
  "v": 1,                    // protocol version — reject mismatches loudly
  "type": "status",          // see table below
  "agent_id": "a3f9",        // stable ID, NOT list index
  "seq": 42,                 // monotonic per agent; gap = lost frame
  "ts": 1733270400.12,       // child-side stamp
  "body": { }                // type-specific
}
```

### Frame types

| `type` | Direction | `body` | Semantics |
|---|---|---|---|
| `hello` | child→orch | `{depth, cmd, pid, name}` | First frame after connect. Registers the agent; carries inherited `MONITOR_AGENT_DEPTH`. Orchestrator rejects if depth ≥ `MONITOR_AGENT_MAX_DEPTH`. |
| `status` | child→orch | `{label}` | Micro-status for the toolbar (e.g. `"Running linter"`). **Coalescing**: only the latest matters — older unread `status` frames may be dropped. |
| `stdout` | child→orch | `{chunk}` | A block of output to surface above the prompt line. Ordered by `seq`. |
| `result` | child→orch | `{ok, summary, data?}` | Terminal success payload. Exactly one per agent on the happy path. |
| `error` | child→orch | `{kind, message, recoverable}` | Structured failure the child *chose* to report. |
| `exit` | child→orch | `{code}` | Clean shutdown notice; child closes after. |
| `heartbeat` | child→orch | `{}` | Liveness ping every N seconds (see failure model). |
| `cancel` | orch→child | `{reason}` | Cooperative cancel request. |

### Lifecycle & failure model

```
connect ──► hello ──► (status | stdout)* ──► result | error ──► exit ──► close
```

The **authoritative failure signal is socket disconnect**, not an exit code:

- Clean termination = `result`/`error` then `exit` then FD closes. Record the
  outcome, no rollback.
- **Dirty disconnect** = FD closes *without* a prior `exit` frame, **or**
  `heartbeat` lapses past timeout → treat the agent as crashed → fire the
  **conversation-history rollback** for that agent's correlation id.
- Be precise in docs and UI: this rollback restores *conversation/history
  state*, not filesystem side effects. True world-rollback would require
  per-agent worktree isolation — out of scope for this protocol.

---

## Part 2 — Thread → prompt_toolkit Bridge

> **Important correction from the original draft.** This codebase does **not**
> run prompt_toolkit via `app.run_async()` on a loop we own. `get_input` uses
> the **synchronous, blocking** `session.prompt(...)` (`conversation.py:473`),
> and prompt_toolkit is already the established input layer (`PromptSession`,
> custom lexer, keybindings — `core/conversation.py`). There is therefore **no
> persistent asyncio loop** for the orchestrator to schedule onto; an event
> loop exists only *during* each blocking `.prompt()` call. The bridge below is
> rewritten for that reality. (The earlier "single-writer on the loop thread,
> no locks" model assumed `run_async` and does **not** apply here.)

### The hazard
Socket frames arrive on **plain reader threads**, while the main thread is
either (a) blocked inside `session.prompt(...)` or (b) synchronously processing
a command / calling the LLM. Touching the prompt_toolkit `Application` or stdout
from a reader thread corrupts the display. The bridge must make background
output safe *during* a prompt, and must not lose frames that arrive *between*
prompts (when no event loop is running at all).

### Components & ownership

```
   ┌─────────────────────────────────────────────────────────────┐
   │ Main thread (synchronous)                                     │
   │   • session.prompt(...) under patch_stdout()  ← during input  │
   │   • command processing / LLM call             ← between inputs│
   │                                                               │
   │   reads (under lock):  status map  +  pending-output queue    │
   │   • bottom_toolbar callable renders status map                │
   │   • flush pending blocks via run_in_terminal (prompt active)  │
   │     or plain print() just before the next prompt              │
   └───────────────▲───────────────────────────────────────────────┘
                   │ writes (under lock)
   ┌───────────────┴──────┐   ┌──────────────────┐
   │ accept thread        │   │ reader thread /N  │  ← parse frames,
   │ (listens on socket)  │──►│ one per agent     │     update shared state
   └──────────────────────┘   └──────────────────┘
```

### The bridge rule (blocking-prompt model → lock-guarded shared state)
There is no loop thread to funnel onto, so the discipline is instead:

- Reader threads parse frames and update **lock-guarded shared state**: a
  `status` map (latest-wins per agent) and a bounded **pending-output queue**
  for `stdout`/`result` blocks. They do **not** print directly.
- **During a prompt:** the prompt runs inside `patch_stdout()`, which makes it
  safe for a small flusher to emit buffered blocks via `run_in_terminal(...)`
  (or `print()` under the patch) without corrupting the cursor. If an
  `Application` is live, a reader may request a redraw via
  `get_app().invalidate()` for the toolbar — guarded so it's a no-op when no
  app is running.
- **Between prompts:** no event loop exists, so frames simply accumulate in the
  shared state and are flushed/printed right before the next `.prompt()` call.

A single lock protects the status map + pending-output queue (the accept thread
also needs it for the connection list). This is less elegant than the
`run_async` single-writer model but is the correct fit for blocking `.prompt()`
— and `patch_stdout` is purpose-built for exactly this "print from background
threads while a prompt is active" case.

### Three display concerns, three mechanisms

1. **Toolbar micro-statuses** — `bottom_toolbar` is a callable that reads the
   (lock-guarded) status map. Reader threads update the map; the toolbar
   re-renders on the next prompt-toolkit refresh, nudged by
   `get_app().invalidate()` when an app is live.
2. **Block output (`stdout`/`result`)** — buffered into the pending-output
   queue, flushed via `run_in_terminal(...)` under the active `patch_stdout()`
   during a prompt, or printed just before the next prompt when idle. Pushes a
   completed block *above* the live prompt line without slicing the cursor.
3. **Prompt input** — unaffected; `session.prompt()` keeps reading keys. Reader
   threads only mutate shared state under the lock, never the input buffer.

### Backpressure & coalescing
- The pending-output queue is **bounded**. On full, drop-and-count `status`
  updates (only the latest matters per agent), but never drop
  `result`/`error`/`exit`.
- Status coalesces in the shared map: the latest `seq` per agent is all the
  toolbar ever needs.

### Index resolution (the dual-index footgun, bridged)
The registry is keyed by **stable `agent_id`**. The numeric `:agent <n>` index
is **never stored** — it's resolved to an `agent_id` at command-parse time
against a snapshot of the current list. A kill that removes an agent therefore
can't silently re-point a stale index.

---

## Part 3 — LLM Result Channel

> Part 2 routes subagent output to the **human terminal** (toolbar, output
> blocks). Part 3 is a **distinct, second consumer** of the *same* frames: the
> orchestrator **LLM's token context**. This is what turns "spawns processes"
> into "an LLM that orchestrates." Implemented in roadmap Phase 8; specified
> here so the design is whole.

### The problem: async subagents vs. synchronous LLM turns
An LLM turn is strictly request→response — it emits tool calls, receives tool
*results*, and continues. But subagents run asynchronously for seconds-to-
minutes and report over the socket. **Nothing re-invokes the LLM when a
subagent finishes**, so the LLM cannot usefully poll; it would busy-wait. The
findings must come back as a **tool result**, synchronously, inside the turn.

### Two consumers, one frame stream
The same `status`/`stdout`/`result`/`error`/`exit` frames feed two sinks:

```
              ┌─► Part 2: human terminal (toolbar + output blocks)
frames ───────┤
              └─► Part 3: LLM context (gather tool → tool result)
```

The reader threads already deposit frames into the lock-guarded shared state
(Part 2). Part 3 adds a second reader of that state: a **blocking gather tool**.

### The gather tool (the keystone)
Prefer a blocking gather over LLM-driven polling:

- `agent_create(prompt) -> {agent_id}` — returns immediately (fire). The LLM
  fires N.
- `agent_gather(ids, timeout) -> {results[]}` — **blocks** the orchestrator
  until all listed agents report a terminal frame (`result`/`error`/`exit`), or
  quorum/timeout is hit, then returns the collected `result`-frame payloads as
  **one tool result**.

This maps cleanly onto the synchronous tool-call model and yields real
parallelism (spawn N, then one wait). Blocking here is fine: the orchestrator
genuinely has nothing to do until findings arrive.

Note: `agent_logfile` returns a *path*, not content — useless for LLM
aggregation. The result channel must return `result`-frame **payloads**
directly.

### Structured summaries, not transcripts
The `result` frame's `summary` field (Part 1) is the unit of aggregation.
Subagents return concise structured findings, never raw transcripts — otherwise
N subagents blow the orchestrator's context window. The `--agent`-mode system
prompt instructs: *"your final `result` is data for an orchestrator; return a
tight, structured summary."*

### Partial-failure honesty
`agent_gather` reports terminal state for **every** requested id — e.g.
`{ok: [...], failed: [{id, reason: "dirty disconnect"}]}`. It never silently
drops a crashed subagent. A crashed child's history rollback (Part 1 failure
model) is local to that child; the orchestrator still receives a structured
"failed/missing" entry so the LLM can act on an accurate picture.

### Orchestrator as sole file writer
- **Researcher** subagents are read-only and safe to fan out wide.
- **Worker** subagents do **not** write the working tree directly by default;
  they return proposed changes, and the **primary orchestrator applies all
  writes serially** as the single writer of record. This sidesteps concurrent-
  write conflicts without per-agent worktree isolation.

### Caps & lifecycle (referenced, detailed in roadmap Phase 8)
- Breadth/sibling cap + total-agent / token budget (depth alone is insufficient);
  child token-costs aggregate up to the orchestrator.
- `agent_send` follow-ups make subagents stateful; define queue-vs-interrupt
  semantics and idle-reaping.

---

## What this pins down
- **Framing**: length-prefixed JSON, versioned envelope, typed bodies — no
  ambiguity about message boundaries.
- **Failure**: disconnect/heartbeat-lapse is the trigger; rollback scope is
  explicitly conversation-history, not the filesystem.
- **The bridge**: blocking `.prompt()` model — reader threads update
  lock-guarded shared state; `patch_stdout()` + `run_in_terminal()` make
  background output safe during a prompt; frames arriving between prompts buffer
  and flush before the next one. (Not the `run_async`/single-writer model from
  the original draft.)
- **Two consumers of one frame stream**: the human terminal (Part 2) and the
  orchestrator LLM's context via the blocking `agent_gather` tool (Part 3).
  Subagents return structured `result` summaries; gather surfaces partial
  failures; the orchestrator is the sole file writer.

## Preserved decisions (do not regress)
- **Synchronous backend stays synchronous.** File tools, token-cost trackers,
  and history loaders remain plain sequential Python. Async/threading is
  quarantined at the edges (socket listener thread + prompt_toolkit loop).
- **Keep logfiles even with sockets.** Socket = live status; logfile =
  full post-mortem transcript. `:agent logs` / `logfile` stay.
