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
- [x] (spike) Module under `src/monitor/tui/` (`spike.py`); REPL imports nothing
      from it. Real build adds `app.py`/`layout.py`/`output_sink.py`.
- [x] (spike) Minimal full-screen `Application`: HSplit(output / info bar /
      input), Ctrl-C/D/Q exit. Verified it constructs + the layout renders.
- [x] (spike) `monitor --tui` launches the screen; `monitor` (no flag) unchanged.

## 1. Sync/async boundary (THE crux)
- [x] (spike) On submit, dispatch the turn to a **worker thread**; backend never
      runs on the UI loop (`SpikeApp._submit`).
- [ ] Disable the input while a turn is processing; re-enable on completion.
      (Spike sets a processing flag but doesn't lock input yet.)
- [x] (spike) Marshal worker→UI updates via `loop.call_soon_threadsafe` +
      `app.invalidate()`.
- [x] (spike) Verified the UI does NOT freeze during a slow turn — the info-bar
      tick keeps advancing (live + a headless off-thread-dispatch test).

## 2. Output routing (rich → output window)
- [x] (spike) Output sink: capture the worker thread's stdout and append to the
      output buffer as `ANSI(...)` formatted text — proven via `_run_and_capture`.
- [x] (spike) **Pin `Application(color_depth=ColorDepth.DEPTH_8_BIT)`** + rich
      `color_system="standard"` so ANSI renders in color (default clamped to
      monochrome). Colors verified in a real terminal.
- [ ] All appends go through one sink abstraction (isolate the rich↔ptk bridge).
- [ ] Capture the REAL backend's stdout (process_input), not just the stub —
      scope the stdout redirect carefully (it's process-global).
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
- [ ] Markdown/code rendering in the output window (rich → ANSI bridge).
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
