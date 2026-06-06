# Checklist: Full-screen TUI for monitor (--tui)

Build-order task list derived from `PLAN_MONITOR_TUI.md`. Scope: **`src/monitor/`
only** (not the `monitor_oop` TUI). Opt-in via `--tui`; the REPL stays the
default and fallback. Check items as completed.

> **Spike done (2026-06-05).** `src/monitor/tui/spike.py` (behind `--tui`,
> `python -m monitor.tui.spike`) + `tests/monitor/tui/test_spike.py` validated
> the hard mechanics with a STUB backend: full-screen 3-region layout (§0),
> worker-thread boundary with no freeze (§1), and rich→ANSI color rendering in
> the output window (§2, after pinning `color_depth`). The real phases below
> replace the stub with `process_input` and build out input/info-bar/agent feed.
> `[x]` items are spike-proven mechanics; the real wiring is still to do.

## 0. Scaffolding (REPL untouched)
- [x] (spike) Add `--tui` flag to argparse in `app.py`.
- [x] (spike) `main()`: if `args.tui` → launch the TUI front-end; else → REPL.
- [x] Module under `src/monitor/tui/`: real `app.py` (`MonitorTUI`); `--tui`
      now launches it. `spike.py` kept as reference. REPL imports nothing from it.
- [x] (spike) Minimal full-screen `Application`: HSplit(output / info bar /
      input), Ctrl-C/D/Q exit. Verified it constructs + the layout renders.
- [x] (spike) `monitor --tui` launches the screen; `monitor` (no flag) unchanged.

## 1. Sync/async boundary (THE crux)  — ✅ Phase 1 (real backend)
- [x] On submit, dispatch the turn to a **worker thread** running the REAL
      `process_input(text, history_file, session)` — backend never runs on the
      UI loop (`MonitorTUI._run_turn`). Backend stays synchronous.
- [x] Input gated while a turn is processing (`_on_accept` ignores submits when
      `processing`); re-enabled on completion. Turn-based: no concurrent turns.
- [x] Marshal worker→UI updates via `loop.call_soon_threadsafe` +
      `app.invalidate()` (completion `done()` + streamed output repaints).
- [x] Verified the UI does NOT freeze during a turn — the info-bar tick keeps
      advancing; headless test asserts `process_input` ran off the UI thread and
      completion marshaled back from the worker. `:exit` exit_flag exits cleanly.

## 2. Output routing (rich → output window)
- [x] (spike) Output sink: capture the worker thread's stdout and append to the
      output buffer as `ANSI(...)` formatted text — proven via `_run_and_capture`.
- [x] (spike) **Pin `Application(color_depth=ColorDepth.DEPTH_8_BIT)`** + rich
      `color_system="standard"` so ANSI renders in color (default clamped to
      monochrome). Colors verified in a real terminal.
- [ ] All appends go through one sink abstraction (isolate the rich↔ptk bridge).
- [x] Capture the REAL backend's stdout: `_OutputSink` (claims `isatty()` so
      rich emits color) is installed via `contextlib.redirect_stdout` for the
      duration of the worker turn ONLY (scoped — process-global but turn-gated).
      Streams writes into the output buffer via `call_soon_threadsafe`.
- [ ] Force the backend's rich console to `color_system="standard"` so its
      palette matches the retro 16-color bar (Phase 2/6 — currently inherits
      rich's auto-detection, downsampled by the 8-bit `color_depth`).
- [ ] Assistant responses + tool output appear in the output window, formatted.
- [ ] Output window scrolls; newest visible; no bleed into the input line.

## 3. Input parity with the REPL
- [ ] Reuse `RedAfter120Lexer`, `CommandCompleter`, function-key bindings,
      history in the input control.
- [ ] Port multi-line input modes + `:command` handling (mirror `get_input` /
      `process_input_mode`).
- [ ] Enter submits; the same validation/format as `get_input` is applied.
- [ ] `:` built-ins and the agent commands (`:agent list/logs/attach/kill/send`)
      work from the TUI input.

## 4. Info bar (live status)
- [ ] Render the current working directory.
- [ ] Render the existing status line (C:/R:/U:/~T:/P:/L:/H:) — locate its
      builder and feed it live (refresh per turn / on token-count change).
- [ ] Render live sub-agent status from `agent_orchestrator.render_toolbar()`.
- [ ] Bar updates via `invalidate()` (periodic refresh + on backend/agent events).

## 5. Sub-agent feed (replaces the REPL bridge)
- [ ] Sub-agent `stdout`/`result` (`drain_pending_output`) → output window via
      `call_soon_threadsafe`.
- [ ] Sub-agent `status` → info bar.
- [ ] In TUI mode, do NOT use `_prompt_with_agent_bridge` (no concurrent printing
      into the input line). Async next-turn injection (8a) is unchanged.
- [ ] Spawn an agent: status shows live in the bar, output streams in the window,
      input stays stable.

## 6. Rendering & UX polish
- [ ] **Preserve the spike's retro look (design spec, not placeholder):**
      reverse-video info bar (`style="reverse"`), 16-color palette only
      (`ColorDepth.DEPTH_8_BIT` + rich `color_system="standard"`, never
      truecolor), full-screen blocked regions + fixed `]]` prompt line,
      monospace/keyboard-first (no mouse chrome, no rounded widgets).
- [ ] Markdown/code rendering in the output window (rich → ANSI bridge) routed
      through `color_system="standard"` so it matches the bar's palette.
- [ ] Scrollback (PgUp/PgDn), and terminal resize handling.
- [ ] Cursor/focus management; clear visual separation of the three regions.

## 7. Hardening & compatibility
- [ ] Ctrl-C cancels the current turn (not the whole app) where feasible; clean
      app exit restores the terminal.
- [ ] Errors in a turn render in the output window, not a crash.
- [ ] REPL path confirmed unchanged (no regressions when `--tui` is absent).
- [ ] `--tui` works alongside `--agent`/orchestration, `--model`, etc.

## 8. Tests
- [ ] Flag routing: `--tui` selects TUI, absence selects REPL (unit on the
      dispatch in `main`).
- [ ] Worker-thread dispatch: a submitted input runs the backend off the UI loop
      and results marshal back (mock backend; assert no UI-thread blocking).
- [ ] Output sink: feeding ANSI text appends renderable content to the buffer.
- [ ] Info bar composes cwd + status line + `render_toolbar()`.
- [ ] Sub-agent frames route to window/bar (drive `agent_orchestrator` with a
      reporter, assert the TUI sink received them).
- [ ] REPL regression guard: existing conversation tests still pass.
