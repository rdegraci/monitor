# Roadmap: Full-screen TUI for monitor (--tui)

Phased delivery from `PLAN_MONITOR_TUI.md` / `CHECKLIST_MONITOR_TUI.md`. Scope:
**`src/monitor/` only** (the `monitor_oop` TUI is a separate effort with its own
docs). Each phase ends shippable; the REPL is the default and a working fallback
throughout, so the TUI can be built incrementally behind `--tui` without
risking the daily driver.

> **Guiding constraint:** one synchronous backend, two shells. The REPL keeps
> working; `--tui` is an additive alternative front-end. No backend logic moves
> into the TUI layer.

> **Spike complete (2026-06-05).** A throwaway `src/monitor/tui/spike.py`
> (behind `--tui`) validated P0 + P1 + thin-P2 with a STUB backend, in a real
> terminal: 3-region layout renders, the worker-thread boundary holds (no
> freeze — the tick keeps moving), and rich/colored/structured output renders in
> the output window (after pinning `color_depth`). **Verdict: green light** —
> the two risky integration points hold; the phases below are now mostly
> mechanical (replace the stub with `process_input`, build out the regions).
> 4 headless tests in `tests/monitor/tui/test_spike.py`.

---

## Phase 0 — Scaffolding  — ✅ spike-validated
**Goal:** `--tui` opens an empty 3-region screen; REPL untouched.
- `--tui` flag; `main()` dispatch (TUI vs REPL); `src/monitor/tui/` module.
- Full-screen `Application`: HSplit(output / info bar / input), exit binding,
  static placeholders.
**Exit:** `monitor --tui` shows the three regions and exits cleanly; `monitor`
is unchanged.
**Risk:** Low.

## Phase 1 — Worker-thread boundary (the crux)  — ✅ DONE (real backend, 2026-06-05)
**Goal:** Run a real turn without freezing the UI.
**Delivered:** `src/monitor/tui/app.py` (`MonitorTUI`) runs the REAL
`process_input` on a worker thread; input gated while processing; worker→UI via
`call_soon_threadsafe` + `invalidate()`; `:exit` exits cleanly. Backend setup is
shared with the REPL via the extracted `conversation.prepare_chat_session()`
(one backend, two shells). `--tui` now launches it. 6 headless tests in
`tests/monitor/tui/test_tui_app.py`; full suite green (1421 passed).
- Submit → backend on a worker thread; input gated while processing.
- Worker→UI updates via `call_soon_threadsafe` + `invalidate()`.
**Exit:** ✅ a real turn runs while the info bar keeps repainting; input
re-enables on completion. (Live single-line turns; pipeline/multiline → Phase 3.)
**Risk:** **High** — *retired.* The boundary holds with the real backend.

## Phase 2 — Output routing  — ✅ DONE (real backend, 2026-06-05)
**Goal:** Real conversation output in the output window.
**Delivered:** `_OutputSink` streams the real backend's stdout into the output
window (single bridge point), scoped via `redirect_stdout` to the worker turn.
The main response path is pygments `TerminalFormatter` = 16-color ANSI (already
retro). Auto-scroll-to-bottom via a `[SetCursorPosition]` marker (`show_cursor=
False`); separate Windows prevent input-line bleed. Test:
`test_output_includes_scroll_to_bottom_marker`.
- Output sink: worker stdout → `ANSI(...)` → output buffer.  ✅
- Responses render and auto-scroll in the window.  ✅
**Exit:** ✅ you can hold a full conversation in the TUI; output shows formatted,
auto-follows newest, input stays put.
**Remaining finesse (→ Phase 6):** force `color_system="standard"` on rich-Console
`:command` features (markdown pager) once those are wired in.
**Risk:** Medium-High — *retired.* The rich↔ptk ANSI bridge holds.

## Phase 3 — Input parity
**Goal:** TUI input behaves like the REPL's.
- Lexer, completer, function keys, history, multi-line modes, `:commands`.
**Exit:** Completion, multi-line, and built-ins (incl. `:agent …`) all work in
the TUI input.
**Risk:** Medium — large surface to port, but well-supported by prompt_toolkit.

## Phase 4 — Info bar  — ✅ DONE (2026-06-05)
**Goal:** Live status region.
**Delivered:** 3-line reverse-video bar — cwd / status line / sub-agent status.
Extracted the REPL's status computation into `conversation.compute_prompt_
display()` (shared source of truth; `chat()` now calls it too), cached +
recomputed once per turn (off the UI thread). ANSI stripped for the bar; the
`monitor <model> ]]` prompt moved to a live callable on the input line. Live
sub-agent status via `render_toolbar()`. 4 tests; full suite green (1427).
- cwd + status line (C:/R:/U:/~T:/P:/L:/H:) + live sub-agent status.  ✅
**Exit:** ✅ the bar shows cwd, live token/cost counts, and agent status,
updating per turn and on repaint.
**Deferred → Phase 6:** model-switch token-window adaptivity (auto-summarize on
`:model` switch) not yet ported to the TUI loop.
**Risk:** Medium — *retired.*

## Phase 5 — Sub-agent feed (the payoff)
**Goal:** Live orchestration UX, no corruption.
- Sub-agent status → info bar; sub-agent output → output window; via
  `call_soon_threadsafe` + `invalidate`. No `_prompt_with_agent_bridge` in TUI.
**Exit:** Spawn an agent → status live in the bar, output streams in the window,
input rock-stable; async next-turn injection still works.
**Risk:** Medium — but the layout makes this clean (the reason for the whole TUI).

## Phase 6 — Hardening & polish
**Goal:** Daily-driver quality.
- Markdown/code rendering, scrollback, resize, Ctrl-C cancels the turn, clean
  exit, REPL regression guard, plays with `--agent`/`--model`.
**Exit:** `--tui` is a viable daily driver; REPL unchanged; full test matrix green.
**Risk:** Medium.

---

## Dependency graph
```
P0 ─► P1 ─► P2 ─► P3 ─► P4 ─► P5 ─► P6
       │
       └── the worker-thread boundary underpins EVERYTHING; P2–P5 all marshal
           through it. If P1 is shaky, the whole TUI feels frozen.
```

## Highest-risk items
1. **P1 worker-thread boundary** — sync backend off the UI loop; the single
   thing that, done wrong, freezes the TUI.
2. **P2 rich ↔ prompt_toolkit output** — capturing ANSI and rendering it in the
   output window without artifacts.
3. **P3 input parity** — porting the REPL's full input behavior (don't ship a
   TUI that's a worse editor than the REPL).

## Out of scope (deferred)
- Replacing the REPL — it stays the default/fallback; `--tui` may become default
  only once proven.
- Mouse support / heavy widgets — keep it keyboard-first.
- `src/monitor_oop/` — separate tree, separate TUI docs.
- Any backend async rewrite — backend stays synchronous (worker-thread only).
