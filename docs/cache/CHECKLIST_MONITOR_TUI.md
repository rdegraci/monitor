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

## 2. Output routing (rich → output window)  — ✅ Phase 2 (real backend)
- [x] **Pin `Application(color_depth=ColorDepth.DEPTH_8_BIT)`** so ANSI renders
      in color (default clamped to monochrome). Verified in a real terminal.
- [x] All appends go through one sink abstraction (`_OutputSink._emit`) — the
      single rich↔ptk bridge point.
- [x] Capture the REAL backend's stdout: `_OutputSink` (claims `isatty()` so
      rich emits color) is installed via `contextlib.redirect_stdout` for the
      duration of the worker turn ONLY (scoped — process-global but turn-gated).
      Streams writes into the output buffer via `call_soon_threadsafe`.
- [x] Also redirect **stderr** to a non-tty `_OutputSink(tty=False)` during the
      turn: the `progress_dots` spinner gates on `sys.stderr.isatty()` and was
      repainting `\r[Processing …]` straight to the terminal (corrupted the input
      line — found in live validation). Non-tty sink → spinner auto-suppresses
      (the info bar's WORKING…/tick is the TUI's activity indicator); genuine
      stderr errors still flow to the output window. Verified end-to-end.
- [x] Assistant responses appear formatted: the main response path uses pygments
      `TerminalFormatter` (`display_output.highlightMarkdown`) which emits
      **16-color ANSI** — already the retro palette, no rich-truecolor leak.
- [x] Output window auto-scrolls / newest visible / no bleed into input: a
      `[SetCursorPosition]` marker at the end of `_output_text` makes the Window
      follow the bottom; `show_cursor=False` hides the marker cursor; the three
      Windows are physically separate so output can't bleed into the input line.
- [ ] (deferred to 6) Force `color_system="standard"` on the few rich-Console
      `:command` features (e.g. the markdown pager) so they match the bar — only
      relevant once those commands are wired into the TUI (Phase 3/6).

## 3. Input parity with the REPL  — ✅ Phase 3 (essentials; multi-line deferred)
- [x] Reuse `RedAfter120Lexer`, `CommandCompleter`, the shared persistent
      `FileHistory`, the REPL `style`, and the REPL key bindings (c-left/c-right
      word nav, f10 voice, **and the F1–F12 preset selector**) — merged into the
      Application. `complete_while_typing=False` matches the REPL.
- [x] **Keep escape-prefixed keys snappy via `ttimeoutlen=0.05`** (default 0.5s).
      ESC is the prefix of EVERY terminal escape sequence, so the vt100 parser
      holds a lone ESC and flushes only after `ttimeoutlen` if the rest arrives
      split — THAT 0.5s wait was the "press twice" lag on PageUp/PageDown/arrows.
      It's the escape-SEQUENCE flush at the parser level — independent of key
      bindings (rebinding the selector's ESC would NOT help). `timeoutlen=0.1`
      (key-mapping completion) lowered too. Raise ttimeoutlen toward ~0.2 if
      running over a slow link where sequences start splitting.
- [x] `:` built-ins and agent commands work from the TUI input — they route
      through the same `process_input`. `;` multi-command (split on `;;;`) and
      `<` macros work on a submitted line.
- [x] Enter submits (single-line). Tab completion, ↑/↓ history recall, and the
      red-past-120 lexer all work via the reused components + ptk defaults.
- [ ] (deferred) Multi-line continuation modes — `|` pipeline and trailing-`\`
      continuation — drive `handle_*` loops on `session.prompt()`, which would
      nest a prompt inside the full-screen app. `|` is **refused gracefully** in
      the TUI (no break); native multi-line composition is a Phase 6 candidate.
      `|` pipelines stay a REPL feature for now.

## 4. Info bar (live status)  — ✅ Phase 4
- [x] Render the current working directory (live `os.getcwd()`, line 1).
- [x] Render the existing status line (C:/R:/U:/~T:/P:/L:/H:): extracted the
      REPL's computation into `conversation.compute_prompt_display()` (one source
      of truth, shared with `chat()`). Cached + recomputed once per turn (it
      tokenizes the whole history — never per repaint). ANSI stripped for the
      clean reverse-video bar. The `monitor <model> <effort> ]]` part becomes the
      input prompt via a callable (live `:model` tracking).
- [x] Render live sub-agent status from `agent_orchestrator.render_toolbar()`
      (line 3; "agents — none" when idle).
- [x] Bar updates via `invalidate()` — the ticker repaints ~2×/s and each turn's
      `done()` invalidates; sub-agent status reflects on next repaint.
- [ ] (deferred) Model-switch token-window adaptivity (REPL recomputes
      MAX_TOKEN_COUNT + may auto-summarize on `:model` switch) is not yet ported
      to the TUI loop — Phase 6 hardening.

## 5. Sub-agent feed (replaces the REPL bridge)  — ✅ Phase 5
- [x] Sub-agent `stdout`/`result` (`drain_pending_output`, lines already prefixed
      `[agent_id]`) → output window. Drained from the ticker (~2×/s) and emitted
      via `_emit` (marshaled with `call_soon_threadsafe`). The TUI is the sole
      drainer in --tui mode.
- [x] Sub-agent `status` → info bar (`render_toolbar()`, done in Phase 4).
- [x] `_prompt_with_agent_bridge` is NOT used in TUI mode (no concurrent printing
      into the input line — output has its own region). Async next-turn injection
      (8a) runs in the backend query path (`drain_pending_injections`), separate
      from the output drain — unchanged.
- [ ] (live-validate) Spawn an agent: status shows live in the bar, output
      streams in the window, input stays stable.

## 6. Rendering & UX polish
- [ ] **Preserve the spike's retro look (design spec, not placeholder):**
      reverse-video info bar (`style="reverse"`), 16-color palette only
      (`ColorDepth.DEPTH_8_BIT` + rich `color_system="standard"`, never
      truecolor), full-screen blocked regions + fixed `]]` prompt line,
      monospace/keyboard-first (no mouse chrome, no rounded widgets).
- [x] Markdown/code rendering: the main response path is pygments
      `TerminalFormatter` (16-color ANSI) → renders in the output window.
- [x] Terminal resize handling — prompt_toolkit's full-screen app handles
      SIGWINCH/re-layout automatically (no code needed).
- [x] Manual scrollback (PgUp/PgDn): driven by a **hidden cursor**
      (`FormattedTextControl.get_cursor_position` → `_cursor_position`), NOT by
      poking `vertical_scroll` — the latter is unreliable with `wrap_lines=True`
      (prompt_toolkit recomputes it each render, which broke PageDown). A
      `_follow` flag pins the cursor to the last line (`_nlines`, tracked
      incrementally); PageUp moves it up a page (scrollback), PageDown to the
      bottom resumes follow. Input keeps focus. (Mouse-wheel still scrolls the
      *terminal* — mouse capture intentionally off, keyboard-first.)
- [x] **Cursor/fragments computed in one locked snapshot** (`_recompute_cursor_
      locked` runs inside `_output_text` under `self._lock`; `_cursor_position`
      returns the stored value). A live cursor recompute raced the output thread
      growing `_nlines`, so `cursor.y` could land past the cached fragment lines
      → `fragment_lines[i]` IndexError mid-render. Guarded by a regression test.
- [x] Cursor/focus management; clear visual separation of the three regions
      (separate Windows + reverse bar; input focused; output cursor hidden).

## 7. Hardening & compatibility  — ✅ Phase 6
- [x] Ctrl-C does NOT quit mid-turn (the sync backend turn can't be safely
      killed; accidental quit is the worse hazard) — shows a note instead. When
      idle, Ctrl-C clears a non-empty input line, else exits cleanly. Ctrl-D/
      Ctrl-Q always exit. (True mid-turn cancel needs backend changes —
      documented, not faked.)
- [x] Errors in a turn render `[error] turn failed` in the output window and the
      app recovers (processing resets) — does not crash or quit. Tested.
- [x] REPL path unchanged: full suite green (1434); `chat()` now delegates to the
      shared `prepare_chat_session` / `compute_prompt_display` /
      `apply_model_switch_if_needed` (same behavior, one source of truth).
- [x] `--tui` works with `--model` (applied before dispatch; the bar/input read
      `config.MODEL` live) and `--agent`/orchestration (the --tui instance is the
      orchestrator UI; sub-agents stay headless).
- [x] `--tui` is launched from the SAME point as `chat()` (end of `main()`), so
      it goes through full setup — `configure_built_ins` / `configure_macros` /
      `configure_runtime_prompt_paths`. (Bug fix: an earlier early-return
      dispatched the TUI before that setup, so `{{macros}}` didn't expand and
      per-project prompt overrides were skipped. Guarded by an ordering test.)
- [x] **Shell commands no longer corrupt the TUI.** Root cause: a shell command
      (git/ls/grep/…) runs via `run_subprocess` which, with `fetch_output=False`,
      *inherits the terminal fds* — so its output wrote over the full-screen
      display (`redirect_stdout` only swaps Python's `sys.stdout`, not fd 1/2).
      Fix, driven by the `needs_tty` flag (step C):
      - **Output-style commands** (`needs_tty=False`, incl. `git`): the TUI sets
        `command_utils.set_output_stream_writer(self._emit)`; `run_subprocess`
        then *pipes* a non-interactive command's stdout/stderr (subprocess-level,
        NOT `os.dup2` — that would fight ptk's own rendering) and streams it into
        the output window. `execute_interactive_command` now passes
        `interactive=command_needs_tty(cmd)` so output commands in the
        interactive list become capturable. REPL behavior unchanged (no writer).
      - **TTY programs** (`needs_tty=True`, e.g. `vim`/`ssh`/`top`/`psql`):
        `_submit` routes them through `run_in_terminal` — suspends the
        full-screen app, hands over the real terminal, then redraws.

## 8. Tests  — ✅ 32 in tests/monitor/tui/test_tui_app.py
- [x] Worker-thread dispatch: backend runs off the UI loop; result marshals back.
- [x] Output sink: stdout+stderr captured into the buffer; scroll marker present.
- [x] Info bar composes cwd + status line + `render_toolbar()`; live model prompt.
- [x] Sub-agent output (`drain_pending_output`) streams into the window.
- [x] Input parity (lexer/completer/history wired); pipeline-mode refusal.
- [x] Ctrl-C mid-turn/idle behavior; model-switch applied after turn; turn-error
      renders without crashing; `:exit` exits.
- [x] Shell command handling: output commands stream to the window via the
      writer seam; TTY commands route to `run_in_terminal`; `command_needs_tty`
      drives the split. (+ command_utils streaming tests, execute_interactive
      interactive-flag tests.)
- [x] REPL regression guard: existing conversation/chat tests still pass.
