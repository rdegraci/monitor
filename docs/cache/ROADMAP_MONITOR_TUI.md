# Roadmap: Full-screen TUI for monitor (--tui)

Phased delivery from `PLAN_MONITOR_TUI.md` / `CHECKLIST_MONITOR_TUI.md`. Scope:
**`src/monitor/` only** (the `monitor_oop` TUI is a separate effort with its own
docs). Each phase ends shippable; the REPL is the default and a working fallback
throughout, so the TUI can be built incrementally behind `--tui` without
risking the daily driver.

> **Guiding constraint:** one synchronous backend, two shells. The REPL keeps
> working; `--tui` is an additive alternative front-end. No backend logic moves
> into the TUI layer.

> **✅ ALL PHASES COMPLETE (2026-06-05).** P0–P6 shipped. `monitor --tui` is a
> viable daily-driver front-end: real backend on a worker thread (no freeze),
> retro 3-region layout, auto-scrolling colored output, real status line + live
> sub-agent feed, input parity (lexer/completer/history/f-keys), and hardening
> (Ctrl-C safety, error recovery, model-switch adaptivity). The REPL is unchanged
> and remains the default. 23 TUI tests; full suite 1434 green. Remaining items
> are optional niceties (manual scrollback, native multi-line, rich-pager color).

> **Post-launch fix — shell command handling (2026-06-08).** Shell commands
> corrupted the TUI because `run_subprocess` inherits the terminal fds (Python's
> `redirect_stdout` doesn't cover fd 1/2). Fixed via a `needs_tty` flag on the
> command JSONs + `command_needs_tty()`: output-style commands (git, ls, …) are
> piped and streamed into the window (`set_output_stream_writer` seam;
> `execute_interactive_command` now passes `interactive=command_needs_tty(cmd)`);
> true TTY programs (vim/ssh/top/…) route through `run_in_terminal` (suspend →
> real terminal → redraw). REPL unchanged. +9 tests; full suite 1449 green. See
> CHECKLIST §7. Live validation of vim/ssh suspend pending.

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

## Phase 3 — Input parity  — ✅ DONE (essentials, 2026-06-05)
**Goal:** TUI input behaves like the REPL's.
**Delivered:** the input `TextArea` reuses the REPL's `RedAfter120Lexer`,
`CommandCompleter`, shared persistent `FileHistory`, `style`, and function-key
bindings (merged into the Application). Tab completion, ↑/↓ history, red-past-120
highlighting, `:` built-ins, `:agent …`, `;` multi-command, and `<` macros all
work. 2 tests. Full suite green (1430).
- Lexer, completer, function keys, history, `:commands`.  ✅
**Exit:** ✅ completion + history + built-ins work in the TUI input.
**Deferred → Phase 6:** multi-line continuation modes (`|` pipeline, trailing-`\`)
nest a `session.prompt()` loop; `|` is refused gracefully (no break). Native
multi-line composition would replace them.
**Risk:** Medium — *retired* for the essentials.

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

## Phase 5 — Sub-agent feed (the payoff)  — ✅ DONE (2026-06-05)
**Goal:** Live orchestration UX, no corruption.
**Delivered:** sub-agent status → info bar (`render_toolbar()`, Phase 4);
sub-agent stdout/result → output window via `_drain_agent_output()` polled from
the ticker and marshaled through `_emit`/`call_soon_threadsafe`. No
`_prompt_with_agent_bridge` in TUI (output has its own region, so no input-line
corruption — the root reason for the whole TUI). Async next-turn injection (8a)
is untouched (separate `drain_pending_injections` in the query path). Test:
`test_drain_agent_output_streams_into_window`. Full suite green (1428).
**Exit:** ✅ status live in the bar, output streams in the window, input stable;
injection still works. (Live agent-spawn validation pending the user.)
**Risk:** Medium — *retired.* The layout made it clean, as predicted.

## Phase 6 — Hardening & polish  — ✅ DONE (2026-06-05)
**Goal:** Daily-driver quality.
**Delivered:** Ctrl-C no longer quits mid-turn (shows a note; clears input /
exits when idle; Ctrl-D/Ctrl-Q always exit); turn errors render `[error]` and
recover (no crash); model-switch token-window adaptivity ported via the shared
`apply_model_switch_if_needed` (extracted from `chat()`); markdown via pygments
16-color; resize is automatic (prompt_toolkit). `--tui` confirmed with
`--model`/`--agent`. REPL unchanged (delegates to the shared helpers). 23 TUI
tests; full suite green (1434).
**Exit:** ✅ `--tui` is a viable daily driver; REPL unchanged; suite green.
**Deferred (future niceties):** manual scrollback (PgUp/PgDn — auto-follow
covers the common case); native multi-line composition (replacing `|` pipeline /
trailing-`\`, currently refused gracefully); forcing `color_system="standard"`
on rich-Console `:command` features (markdown pager).
**Risk:** Medium — *retired.*

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
