"""Full-screen TUI front-end for monitor (`--tui`) — PLAN_MONITOR_TUI Phase 1.

The REAL implementation (replaces the spike's stub backend with the actual
`process_input` turn pipeline), keeping the spike's proven retro look:

- **Three regions** — output window / reverse-video info bar / input line.
- **The sync/async boundary (the crux):** the backend (`process_input`, the LLM
  call, file tools) is synchronous and STAYS that way. On submit it runs in a
  WORKER THREAD; the UI event loop stays free so the info-bar tick keeps moving
  and output streams in — no freeze. Worker→UI updates are marshaled via
  `loop.call_soon_threadsafe` + `app.invalidate()`.
- **Output routing:** during a turn, stdout is redirected to a streaming sink
  whose writes flow into the output window as `ANSI(...)` — so the backend's
  rich/colored output renders in its own region and never corrupts the input
  line (the root problem the REPL bridge couldn't solve).

Retro identity (PLAN "Visual identity"): reverse-video info bar, the 16-color
palette via `ColorDepth.DEPTH_8_BIT`, full-screen blocked regions, monospace /
keyboard-first.

Scope notes (Phase 1):
- Input is single-line. Pipeline/backslash/multi-line continuation modes (which
  would nest a `session.prompt()`) are Phase 3 (input parity).
- The info bar shows cwd + state + a live tick; the full status line
  (C:/R:/U:/~T:/…) and model-switch adaptivity are Phase 4.
- The REPL remains the default and a working fallback; this module is opt-in via
  `--tui` and the REPL path imports nothing from here.

Run via `monitor --tui`.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import re
import threading

from prompt_toolkit.application import Application, run_in_terminal
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.widgets import TextArea

from monitor import config
# Input parity (Phase 3): reuse the REPL's lexer / completer / history / style /
# key bindings so the TUI input behaves like the REPL prompt — including the
# function-key preset selector (F1–F12). `bindings`/`style` are populated by
# create_prompt_session() (via prepare_chat_session in __init__) before we build
# the Application. The f-key selector binds a bare `escape`, which would make
# escape-prefixed keys (PageUp/arrows) wait to disambiguate — we keep them snappy
# by lowering the Application's `timeoutlen` (see below) rather than dropping the
# selector.
from monitor.lib.lexer import (
    RedAfter120Lexer,
    CommandCompleter,
    history as _repl_history,
    bindings as _repl_bindings,
    style as _repl_style,
)
from monitor.core.conversation import (
    prepare_chat_session,
    compute_prompt_display,
    apply_model_switch_if_needed,
    process_input,
    flush_logs_and_conversation,
    _maybe_report_agent_result,
    _agent_is_one_shot,
)
from monitor.core.commands import command_needs_tty
from monitor.lib.command_utils import set_output_stream_writer

logger = logging.getLogger(__name__)

# Soft cap on retained output text (Phase 6 will add real scrollback). Keeps a
# long session from growing the buffer without bound; we trim from the front.
_MAX_OUTPUT_CHARS = 400_000

# Strip SGR color codes: the status line carries red/yellow/blue ANSI that would
# clash with the reverse-video info bar. A clean monochrome reverse bar reads as
# more retro anyway (PLAN "Visual identity").
_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_SGR_RE.sub("", s or "")


class _OutputSink(io.TextIOBase):
    """Process-global stdout/stderr for the duration of a worker turn.

    Each write streams text into the TUI's output buffer (on the worker thread,
    under the app's lock) and schedules a coalesced repaint on the UI loop, so
    the backend's rich/ANSI output flows into the output window live without
    touching the input line.

    ``tty`` controls what ``isatty()`` reports:
    - stdout sink → ``True`` so rich/pygments emit color (rendered at the app's
      pinned `color_depth`).
    - stderr sink → ``False`` so the progress spinner (`progress_dots`, which
      gates on ``sys.stderr.isatty()`` and repaints ``\\r[Processing …]``
      directly to the terminal) auto-suppresses under the TUI. The info bar's
      WORKING…/tick is the TUI's own activity indicator. Genuine stderr error
      text still flows into the output window.
    """

    def __init__(self, app: "MonitorTUI", *, tty: bool = True):
        self._app = app
        self._tty = tty

    def write(self, s):  # noqa: D401 - file-like
        if s:
            self._app._emit(s)
        return len(s) if s else 0

    def flush(self):
        pass

    def isatty(self):
        return self._tty


class MonitorTUI:
    def __init__(self):
        # Shared backend setup (history, query registration, prompt session).
        # Same call the REPL makes — one backend, two shells.
        self.session, self.history_file = prepare_chat_session()

        self._chunks = [
            "monitor --tui (Phase 1)\n"
            "Type a message and press Enter. The turn runs on a worker thread; "
            "watch the tick in the info bar keep moving while the model thinks — "
            "that's the UI staying live. Ctrl-C / Ctrl-D / Ctrl-Q exits.\n"
        ]
        self._lock = threading.Lock()
        self.processing = False
        self.tick = 0
        self.loop = None
        self._stop = threading.Event()
        self._render_pending = False
        # Cache of resolved output fragments — rebuilt only when output changes
        # (see _emit), NOT on every repaint. Without this, each keystroke / tick
        # re-parsed the whole ANSI buffer (~1s when large → per-letter input lag).
        self._render_cache = None
        self._total_chars = sum(len(c) for c in self._chunks)
        # Scrollback: a hidden cursor drives the output Window's scroll position
        # (robust with wrap_lines, unlike manually poking vertical_scroll). While
        # following, the cursor sits on the last line (pinned to bottom); PageUp
        # moves it up (scrollback), PageDown to the bottom resumes follow.
        self._follow = True
        self._scroll_line = 0
        self._nlines = sum(c.count("\n") for c in self._chunks)
        # The scroll cursor, computed together with the fragment cache under the
        # lock so its y can never exceed the cached fragments' line count (a live
        # recompute raced the output thread → IndexError during streaming).
        self._cache_cursor = Point(x=0, y=0)

        # The status line (C:/R:/U:/~T:/P:/L:/H:), recomputed once per turn (it
        # tokenizes the full history — never per-repaint). Seed it at startup.
        self._status_line = ""
        self._recompute_status()

        # Track the active model so a :model switch mid-session adapts the token
        # window (and may auto-summarize) just like the REPL loop does.
        self._last_model = getattr(config, "MODEL", None)

        self.input = TextArea(
            height=1,
            multiline=False,
            # Callable prompt → BeforeInput re-evaluates it each render, so the
            # `monitor <model> <effort> ]]` prompt tracks :model switches live.
            prompt=self._input_prompt,
            accept_handler=self._on_accept,
            # Input parity with the REPL: same lexer (red past col 120),
            # completer (:commands + paths, tab-triggered), and shared persistent
            # history (↑/↓ recall, same ~/.chat_session_history file as the REPL).
            lexer=RedAfter120Lexer(),
            completer=CommandCompleter(),
            complete_while_typing=False,
            history=_repl_history,
        )
        # show_cursor=False: the cursor is invisible but its position (from
        # _cursor_position) drives the Window's scroll — bottom while following,
        # else the paged-to line.
        self.output_window = Window(
            FormattedTextControl(
                self._output_text,
                show_cursor=False,
                get_cursor_position=self._cursor_position,
            ),
            wrap_lines=True,
        )
        body = HSplit([
            self.output_window,
            # Reverse-video info bar — the retro signature (PLAN Visual identity):
            # cwd / status line / live sub-agent status.
            Window(FormattedTextControl(self._info_text), height=3, style="reverse"),
            self.input,
        ])

        kb = KeyBindings()

        @kb.add("c-d")
        @kb.add("c-q")
        def _exit(event):
            self._stop.set()
            event.app.exit()

        @kb.add("c-c")
        def _ctrl_c(event):
            self._ctrl_c_action()

        # Scrollback for the output window (input keeps focus). PageUp drops into
        # scrollback (stops auto-following); PageDown to the bottom resumes follow.
        @kb.add("pageup")
        def _(event):
            self._scroll_output(-1)

        @kb.add("pagedown")
        def _(event):
            self._scroll_output(+1)

        self.app = Application(
            layout=Layout(body, focused_element=self.input),
            # Merge the REPL's bindings (c-left/c-right word nav, f10 voice, and
            # the F1–F12 preset selector) with the TUI's own (exit, ctrl-c,
            # scrollback). The selector's tab/enter/escape bindings are filtered
            # to its preview state, so they don't disturb normal completion/submit.
            key_bindings=merge_key_bindings([kb, _repl_bindings]),
            # Reuse the REPL's style so the lexer's style classes resolve.
            style=_repl_style,
            full_screen=True,
            # Pin the 16-color depth so ANSI renders in color AND keeps the retro
            # palette (default detection clamps to monochrome / would allow
            # truecolor). See PLAN "Visual identity".
            color_depth=ColorDepth.DEPTH_8_BIT,
        )
        # Keep escape-prefixed keys (PageUp/PageDown/arrows) snappy. ESC is the
        # prefix of EVERY terminal escape sequence, so prompt_toolkit's parser
        # briefly holds a lone ESC waiting for the rest; if the bytes arrive
        # split, it flushes only after `ttimeoutlen` (default 0.5s) — THAT wait
        # is the "have to press twice" lag. It's the escape-SEQUENCE flush, at
        # the parser level, independent of which keys are bound (so rebinding the
        # f-key selector's ESC wouldn't help). `timeoutlen` (default 1.0s) is the
        # separate key-MAPPING completion timeout (e.g. enter's ControlM/ControlJ
        # pair). Lower both so a single tap registers near-instantly. (If you run
        # the TUI over a slow link and sequences start splitting, raise
        # ttimeoutlen back toward ~0.2.)
        self.app.ttimeoutlen = 0.05
        self.app.timeoutlen = 0.1

    # --- region content -----------------------------------------------------

    def _output_text(self):
        with self._lock:
            if self._render_cache is None:
                # Resolve ANSI → fragments ONCE per output change — cached, NOT
                # re-parsed per repaint. Recompute the scroll cursor in the SAME
                # locked snapshot so cursor.y stays within these fragments' lines.
                text = "".join(self._chunks)
                self._render_cache = to_formatted_text(ANSI(text))
                self._recompute_cursor_locked()
            return self._render_cache

    def _recompute_cursor_locked(self):
        """Set the scroll cursor consistent with the current buffer. Caller MUST
        hold self._lock. y == _nlines is the last line index (line_count-1), so
        it can't exceed the fragment list built from the same snapshot."""
        y = self._nlines if self._follow else min(self._scroll_line, self._nlines)
        self._cache_cursor = Point(x=0, y=max(0, y))

    def _cursor_position(self):
        # Return the stored cursor (computed under the lock with the fragments),
        # NOT a live recompute — that raced the output thread (IndexError).
        with self._lock:
            return self._cache_cursor

    def _input_prompt(self):
        """The `monitor <model> <effort> ]] ` input prompt (live model)."""
        model = getattr(config, "MODEL", "") or ""
        prefix = getattr(config, "REASONING_MODEL_PREFIX", "") or ""
        effort = getattr(config, "REASONING_EFFORT", "") or ""
        reasoning = effort if (isinstance(model, str) and prefix and prefix in model) else ""
        return f"monitor {model} {reasoning} ]] "

    def _recompute_status(self) -> None:
        """Recompute the cached status line (C:/R:/U:/…). Called once per turn +
        at startup — NOT per repaint (it tokenizes the whole history)."""
        try:
            raw = compute_prompt_display()
        except Exception:
            logger.debug("status recompute failed", exc_info=True)
            return
        plain = _strip_ansi(raw)
        # The stats block starts at the line carrying H: and may now include
        # a following cache-composition line. cwd + the `monitor … ]]` prompt
        # line are rendered separately (live cwd / input).
        stats_lines = []
        lines = plain.splitlines()
        for index, line in enumerate(lines):
            if "H:" not in line:
                continue
            stats_lines.append(line.strip())
            if index + 1 < len(lines) and lines[index + 1].strip().startswith("Cache "):
                stats_lines.append(lines[index + 1].strip())
            break
        self._status_line = "\n".join(stats_lines)

    def _agent_status(self) -> str:
        try:
            from monitor.lib import agent_orchestrator as orch
            return _strip_ansi(orch.render_toolbar() or "").strip()
        except Exception:
            return ""

    def _drain_agent_output(self) -> None:
        """Pull queued sub-agent stdout/result lines (already prefixed with
        ``[agent_id]``) and stream them into the output window — the live
        orchestration feed (PLAN Phase 5). Polled from the ticker. The TUI is the
        sole drainer in --tui mode (the REPL's _prompt_with_agent_bridge is not
        used here). Result→next-turn injection (8a) runs separately in the
        backend query path and is unaffected."""
        try:
            from monitor.lib import agent_orchestrator as orch
            lines = orch.drain_pending_output()
        except Exception:
            return
        for line in lines:
            self._emit(line if line.endswith("\n") else line + "\n")

    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def _info_text(self):
        cwd = os.getcwd()
        agents = self._agent_status() or "agents — none"
        if self.processing:
            state = f"working {self._SPINNER[self.tick % len(self._SPINNER)]}"
        else:
            state = "idle"
        return (
            f" {cwd}\n"
            f" {self._status_line}   [{state}]\n"
            f" {agents}"
        )

    def _has_agent_activity(self) -> bool:
        try:
            from monitor.lib import agent_orchestrator as orch
            return bool(orch.has_active_agents())
        except Exception:
            return False

    # --- output sink (streamed from the worker turn) ------------------------

    def _emit(self, s: str) -> None:
        if not s:
            return
        with self._lock:
            self._chunks.append(s)
            self._total_chars += len(s)
            self._nlines += s.count("\n")
            # Trim from the front past the soft cap (running totals — O(1)
            # amortized, not an O(n) re-sum every write). Removing front lines
            # shifts line numbers, so adjust the scrollback anchor too.
            while self._total_chars > _MAX_OUTPUT_CHARS and len(self._chunks) > 1:
                popped = self._chunks.pop(0)
                self._total_chars -= len(popped)
                removed_nl = popped.count("\n")
                self._nlines -= removed_nl
                self._scroll_line = max(0, self._scroll_line - removed_nl)
            self._render_cache = None  # output changed → rebuild fragments next render
        self._schedule_render()

    def _schedule_render(self) -> None:
        # Coalesce repaints: many tiny writes during a turn → at most one pending
        # invalidate on the UI loop at a time.
        if self.loop is None or self._render_pending:
            return
        self._render_pending = True

        def _do():
            self._render_pending = False
            self.app.invalidate()

        try:
            self.loop.call_soon_threadsafe(_do)
        except Exception:
            self._render_pending = False

    # --- scrollback ---------------------------------------------------------

    def _scroll_output(self, direction: int) -> None:
        """Scroll the output window by ~a page (direction: -1 up, +1 down) by
        moving the hidden scroll cursor; the Window scrolls to keep it visible.
        Paging up enters scrollback (stops following); paging down to the bottom
        resumes follow. No-op until the window has rendered at least once."""
        info = self.output_window.render_info
        if info is None:
            return
        page = max(1, info.window_height - 1)
        last = self._nlines
        # On leaving follow, anchor the scroll cursor at the current bottom.
        if self._follow:
            self._scroll_line = last
        if direction < 0:
            self._scroll_line = max(0, self._scroll_line - page)
            self._follow = False
        else:
            self._scroll_line += page
            if self._scroll_line >= last:      # reached the bottom → resume follow
                self._scroll_line = last
                self._follow = True
            else:
                self._follow = False
        with self._lock:
            self._recompute_cursor_locked()
        self.app.invalidate()

    # --- input → worker-thread turn (the crux) ------------------------------

    def _ctrl_c_action(self) -> None:
        # Don't quit mid-turn (the backend turn is a blocking call on a worker
        # thread — there's no safe way to kill it, and accidentally quitting
        # during a long turn is the bigger hazard). When idle, Ctrl-C clears a
        # non-empty input line (shell-like), else exits.
        if self.processing:
            self._emit(
                "\n[a turn is running — Ctrl-C can't cancel it yet; "
                "wait for it to finish, then Ctrl-D/Ctrl-Q to quit]\n"
            )
            self.app.invalidate()
            return
        buf = self.input.buffer
        if buf.text:
            buf.reset()
            return
        self._stop.set()
        self.app.exit()

    def _on_accept(self, buff):
        text = buff.text
        # Gate: ignore submits while a turn is in flight (turn-based; no
        # concurrent turns). This is how "input is disabled while processing".
        if self.processing or not text.strip():
            return False  # clear the buffer
        # Pipeline mode (leading "|") drives the REPL's continuation prompting
        # (handle_pipeline_command loops on session.prompt) — that would nest a
        # prompt inside the full-screen app. Refuse gracefully; it stays a REPL
        # feature for now (Phase 6 may add native multi-line composition).
        if text.lstrip().startswith("|"):
            self._emit(
                "\n[pipeline mode (|) isn't available in --tui yet — use the REPL "
                "for | pipelines; ; multi-command and : built-ins work here]\n"
            )
            self.app.invalidate()
            return False
        self._submit(text)
        return False  # clear the buffer

    def _submit(self, text: str) -> None:
        self.processing = True
        self._emit(f"\n> {text}\n")
        self.app.invalidate()
        if command_needs_tty(text):
            # Needs a real terminal (vim/ssh/top/psql/…): suspend the full-screen
            # app and hand the terminal to the command, then redraw. Runs inline
            # via run_in_terminal (NOT the worker thread) so the app is paused.
            self._run_tty_turn(text)
        else:
            # Output-style command or LLM turn: run on the worker thread; output
            # (incl. captured subprocess output) streams into the window.
            threading.Thread(
                target=self._run_turn, args=(text,), name="tui-worker", daemon=True
            ).start()

    def _run_tty_turn(self, text: str) -> None:
        """Run a TTY command by suspending the full-screen app so the command
        owns the real terminal (run_in_terminal), then redrawing. Runs on the UI
        thread (the app is paused), which is correct here — we WANT to block
        until the interactive program exits."""
        state = {"exit": False}

        def work():
            # App rendering suspended; the command owns the real terminal.
            try:
                state["exit"] = bool(process_input(text, self.history_file, self.session))
            except Exception:
                logger.exception("TUI tty turn failed")
            try:
                flush_logs_and_conversation()
            except Exception:
                logger.exception("Failed flushing logs after tty turn")
            try:
                self._last_model = apply_model_switch_if_needed(self._last_model)
            except Exception:
                logger.debug("model switch handling failed", exc_info=True)
            self._recompute_status()

        def done(_fut):
            self.processing = False
            self._emit(f"[ran: {text}]\n")
            if state["exit"]:
                self._stop.set()
                self.app.exit()
            else:
                self.app.invalidate()

        try:
            fut = run_in_terminal(work)
            if hasattr(fut, "add_done_callback"):
                fut.add_done_callback(done)
            else:
                done(fut)
        except Exception:
            # Degrade gracefully rather than corrupt the screen.
            logger.exception("run_in_terminal failed")
            self.processing = False
            self._emit("\n[could not run interactive command in --tui]\n")
            self.app.invalidate()

    def _run_turn(self, text: str) -> None:
        """Runs OFF the UI thread. Executes one real backend turn with stdout
        redirected into the output window, then marshals completion back."""
        exit_flag = False
        reported = False
        out_sink = _OutputSink(self, tty=True)    # color for rich/pygments
        err_sink = _OutputSink(self, tty=False)   # non-tty → spinner suppresses
        try:
            with contextlib.redirect_stdout(out_sink), contextlib.redirect_stderr(err_sink):
                exit_flag = bool(process_input(text, self.history_file, self.session))
                # React to a :model switch made during this turn (updates the
                # token window / may auto-summarize). Inside the redirect so any
                # summary/warning output lands in the output window, not the term.
                try:
                    self._last_model = apply_model_switch_if_needed(self._last_model)
                except Exception:
                    logger.debug("model switch handling failed", exc_info=True)
        except Exception:
            logger.exception("TUI turn failed")
            self._emit("\n[error] turn failed — see logs\n")
        finally:
            try:
                flush_logs_and_conversation()
            except Exception:
                logger.exception("Failed flushing logs after TUI turn")
            # Parity with the REPL loop: if this instance is a spawned sub-agent,
            # report the turn's result so orchestration still works under --tui.
            try:
                reported = _maybe_report_agent_result(text)
            except Exception:
                logger.debug("agent result report failed", exc_info=True)
            # Refresh the status line for the next prompt (off the UI thread).
            self._recompute_status()

        def done():
            self.processing = False
            # Exit on :exit, or when a one-shot sub-agent has reported its result.
            if exit_flag or (reported and _agent_is_one_shot()):
                self._stop.set()
                self.app.exit()
            else:
                self.app.invalidate()

        if self.loop is not None:
            self.loop.call_soon_threadsafe(done)

    # --- lifecycle ----------------------------------------------------------

    def _on_start(self) -> None:
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()
        # Route non-interactive subprocess output (git, ls, grep, …) into the
        # output window instead of letting it write to / corrupt the terminal.
        set_output_stream_writer(self._emit)
        threading.Thread(
            target=self._ticker, name="tui-ticker", daemon=True
        ).start()

    def _ticker(self) -> None:
        # Pumps the live sub-agent feed and animates the working spinner. Only
        # forces a repaint when something is actually changing (a turn running,
        # or active agents) — when idle it does NOT repaint, so it never competes
        # with keystroke rendering. (Sub-agent output repaints itself via _emit.)
        import time as _time
        while not self._stop.is_set():
            _time.sleep(0.5)
            self.tick += 1
            self._drain_agent_output()   # stream sub-agent output → window
            if (self.processing or self._has_agent_activity()) and self.loop is not None:
                try:
                    self.loop.call_soon_threadsafe(self.app.invalidate)
                except Exception:
                    break

    def run(self) -> None:
        try:
            self.app.run(pre_run=self._on_start)
        finally:
            # Clear the process-global subprocess sink we installed in
            # _on_start. It's a bound method on THIS instance; leaving it set
            # would route later in-process subprocess output into a dead TUI
            # (and leak across tests that build/tear down a TUI).
            set_output_stream_writer(None)


def run() -> None:
    MonitorTUI().run()


if __name__ == "__main__":
    run()
