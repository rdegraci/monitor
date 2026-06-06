# Plan: Full-screen TUI for monitor (--tui)

> Scope: **`src/monitor/` only.** This is NOT the `src/monitor_oop/` TUI effort
> (`TUI_PLAN.md` / `PLAN_SCROLL_TUI.md` are that tree's — do not reuse them).
> Design spec, not implemented code.
>
> Goal: an opt-in **full-screen, three-region TUI** front-end selected with
> `--tui`, running the **same synchronous backend** as today. The existing REPL
> stays the default and a working fallback.

> **Spike validated (2026-06-05).** A throwaway `src/monitor/tui/spike.py`
> (P0 + P1 + thin P2, behind `--tui`) proved the two hard points in a real
> terminal: the **worker-thread boundary holds** (the info-bar tick keeps moving
> during a ~1.5s turn — no UI freeze), the **prompt stays put** while output
> renders, and **rich/colored/structured output** (colors, styles, a `Table`)
> renders in the output window. Key learning: **pin the Application's
> `color_depth`** (`ColorDepth.DEPTH_8_BIT`) — default detection clamped ANSI to
> monochrome — and emit simple SGR via rich `color_system="standard"`. No
> landmines surfaced; the remaining phases are mechanical.

## Why

The REPL (`while True: get_input(); process_input()`) can't show live
sub-agent activity without corruption: concurrent `print()` from a background
thread fights prompt_toolkit's redraw of the single input line (this is why the
live-flush attempt made the prompt vanish). A full-screen layout fixes it at the
root — output gets its own region, the input never moves. It also gives the
async orchestration UX (fire-and-continue) a proper home: live status + live
output + a stable input, all driven by one event loop.

## The three regions

```
┌──────────────────────────────────────────────────────────────┐
│ output window  (scrollable conversation + tool/agent output)   │  ← grows
│                                                                │
├──────────────────────────────────────────────────────────────┤
│ info bar:  <cwd>   C:…(%)  R:…  U:…  (~T:$…  P:$…)  L:…  H:…    │  ← 1–2 lines
│            agents — <id>: <status>   <id2>: <status2>          │
├──────────────────────────────────────────────────────────────┤
│ input:  monitor openai/gpt-5.4-mini medium ]] _                │  ← prompt
└──────────────────────────────────────────────────────────────┘
```

- **Output window** — a scrollable buffer; assistant responses, tool output, and
  streamed sub-agent output land here. Never interleaved with the input line.
- **Info bar** — the current working directory, the existing status line
  (`C:context / R:remaining / U:used / ~T:cost / P:prompt-cost / L:last / H:history`),
  and the **live sub-agent status** (from `agent_orchestrator.render_toolbar()`).
- **Input area** — the `monitor <model> <effort> ]]` prompt, with the same
  editing/lexer/completion behavior as the REPL.

## Architecture

A persistent **prompt_toolkit `Application`** owns the event loop and the layout
(an `HSplit` of the three regions). Key pieces:

### The sync/async boundary (the crux)
The backend — `process_input`, the LLM call, file tools, token tracking — is
**synchronous and blocking** and STAYS that way. If it runs on the UI event-loop
thread, the whole TUI freezes while the model thinks. So:
- On input submit, dispatch the turn to a **worker thread** (a dedicated thread
  or `loop.run_in_executor`).
- The worker's output and any background updates marshal back to the UI via
  `loop.call_soon_threadsafe(...)` + `app.invalidate()`.
- While the worker runs, the input is disabled (the conversation is turn-based)
  but the **event loop stays free** — so the info bar (token counts, sub-agent
  status) and output window keep updating live. No freeze.

This is the `run_async` bridge the orchestration PLAN described but didn't take
(because we kept the REPL). The TUI is where it pays off.

### Output routing
Backend code prints via `rich`/`pygments` (markdown, syntax highlighting) to
stdout. In the TUI, that output must land in the output window:
- Capture the worker thread's stdout (a redirect/sink), and append it to the
  output buffer as **`ANSI(...)`** formatted text (rich emits ANSI; prompt_toolkit
  renders ANSI), via `call_soon_threadsafe`.
- This is the fiddliest integration (rich ↔ prompt_toolkit); isolate it behind a
  single output-sink abstraction.
- **Pin the Application's `color_depth`** (spike-proven): default detection
  clamps ANSI to monochrome. Use `ColorDepth.DEPTH_8_BIT` + rich
  `color_system="standard"` (simple 16-color SGR) for portable color; bump to
  `DEPTH_24_BIT`/`truecolor` only for terminals known to support it.

### Input control
Reuse the REPL's input machinery in the input window: the `RedAfter120Lexer`,
the `CommandCompleter`, function-key bindings, history, multi-line input modes,
and `:command` handling. prompt_toolkit supports all of this inside a full
`Application` — it's a careful port of what `get_input` / `create_prompt_session`
already do, not a reinvention.

### Sub-agent feed (the payoff)
The orchestration listener threads already collect frames into
`agent_orchestrator`'s lock-guarded state. The TUI subscribes:
- sub-agent `status` → the **info bar** (`render_toolbar()`),
- sub-agent `stdout`/`result` → the **output window** (`drain_pending_output()`),
- both pushed via `call_soon_threadsafe` + `invalidate()` on new frames.

This **replaces** the REPL-only `_prompt_with_agent_bridge` hack: no concurrent
printing into the input line, so no corruption. Async result injection into the
LLM's next turn (PLAN 8a) is unchanged — the TUI is purely a better renderer.

## Flag-gating
- Add `--tui` to argparse. `main()`: if `args.tui`, launch the TUI front-end;
  otherwise run the existing REPL **unchanged**.
- Both front-ends call the **same backend** (`process_input`, `query`, the
  orchestration tools). The TUI is an alternative shell, not a fork of logic.
- New code lives under `src/monitor/tui/` (or a single module to start) so the
  REPL path is untouched and the TUI is removable.

## Visual identity (retro — adopt the spike's look as the spec)

The spike's aesthetic is a **deliberate design target**, not placeholder styling.
The real build must preserve the retro feel; do NOT "modernize" it. Concrete,
load-bearing choices (lose any one and the retro character degrades):

- **Reverse-video info bar** (`style="reverse"`) — the inverted status strip is
  the strongest retro signal. Keep the bar inverted, not a subtle modern accent.
- **16-color palette, never truecolor** — `ColorDepth.DEPTH_8_BIT` +
  rich `color_system="standard"`. The limited, slightly-saturated 16-color SGR
  look IS the retro feel; truecolor gradients read as modern. (Already pinned in
  *Output routing* for correctness — it's also an aesthetic decision.)
- **Full-screen blocked regions** with hard separators and a fixed prompt line
  (`monitor <model> <effort> ]] `) — the classic three-pane TUI silhouette.
- **Monospace, keyboard-first, no mouse chrome / no rounded widgets** — keep it
  text-terminal, not a GUI-in-a-terminal.

When the real backend's rich output flows into the window (P2), route it through
the same `color_system="standard"` so its colors match the bar's palette — one
consistent 16-color world, not two.

## What this pins down
- **Three regions, one event loop** — output/info/input as separate windows;
  the input never moves, output never corrupts it.
- **Sync backend, UI never freezes** — backend runs in a worker thread; the loop
  marshals results back. No async rewrite of the backend.
- **Opt-in & reversible** — `--tui` selects it; the REPL is the default and
  fallback until the TUI is proven.
- **Orchestration unchanged** — the TUI renders `agent_orchestrator` data; the
  frame protocol, caps, lifecycle, and async injection are as-is.

## Preserved decisions (do not regress)
- **Backend stays synchronous.** Quarantine async to the UI shell + the
  worker-thread boundary; do not asyncify file tools / token trackers / history.
- **REPL remains the default and a working fallback.** Ship the TUI behind
  `--tui`; do not delete or degrade the REPL path.
- **One backend, two shells.** No business logic in the TUI layer — it only
  renders and dispatches.
