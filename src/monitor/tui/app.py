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
import threading

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI, merge_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.widgets import TextArea

from monitor import config
from monitor.core.conversation import (
    prepare_chat_session,
    process_input,
    flush_logs_and_conversation,
    _maybe_report_agent_result,
    _agent_is_one_shot,
)

logger = logging.getLogger(__name__)

# Soft cap on retained output text (Phase 6 will add real scrollback). Keeps a
# long session from growing the buffer without bound; we trim from the front.
_MAX_OUTPUT_CHARS = 400_000


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

        self.input = TextArea(
            height=1,
            multiline=False,
            prompt="monitor ]] ",
            accept_handler=self._on_accept,
        )
        body = HSplit([
            # show_cursor=False: the [SetCursorPosition] marker in _output_text
            # drives auto-scroll-to-bottom without drawing a cursor block here.
            Window(
                FormattedTextControl(self._output_text, show_cursor=False),
                wrap_lines=True,
            ),
            # Reverse-video info bar — the retro signature (PLAN Visual identity).
            Window(FormattedTextControl(self._info_text), height=2, style="reverse"),
            self.input,
        ])

        kb = KeyBindings()

        @kb.add("c-c")
        @kb.add("c-d")
        @kb.add("c-q")
        def _exit(event):
            self._stop.set()
            event.app.exit()

        self.app = Application(
            layout=Layout(body, focused_element=self.input),
            key_bindings=kb,
            full_screen=True,
            # Pin the 16-color depth so ANSI renders in color AND keeps the retro
            # palette (default detection clamps to monochrome / would allow
            # truecolor). See PLAN "Visual identity".
            color_depth=ColorDepth.DEPTH_8_BIT,
        )

    # --- region content -----------------------------------------------------

    def _output_text(self):
        with self._lock:
            text = "".join(self._chunks)
        # Append a [SetCursorPosition] marker at the end: FormattedTextControl
        # places the (hidden) cursor there and the containing Window scrolls to
        # keep it visible — i.e. the output window auto-follows the newest line.
        return merge_formatted_text([ANSI(text), [("[SetCursorPosition]", "")]])

    def _info_text(self):
        state = "WORKING…" if self.processing else "idle"
        cwd = os.getcwd()
        model = getattr(config, "MODEL", "?")
        # Phase 4 swaps the second line for the real status line
        # (C:/R:/U:/~T:/P:/L:/H:) + live sub-agent status.
        return (
            f" {cwd}\n"
            f" {model}   [{state}]   tick {self.tick}"
        )

    # --- output sink (streamed from the worker turn) ------------------------

    def _emit(self, s: str) -> None:
        with self._lock:
            self._chunks.append(s)
            # Trim from the front if we exceed the soft cap (cheap; Phase 6 adds
            # proper scrollback).
            total = sum(len(c) for c in self._chunks)
            while total > _MAX_OUTPUT_CHARS and len(self._chunks) > 1:
                total -= len(self._chunks.pop(0))
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

    # --- input → worker-thread turn (the crux) ------------------------------

    def _on_accept(self, buff):
        text = buff.text
        # Gate: ignore submits while a turn is in flight (turn-based; no
        # concurrent turns). This is how "input is disabled while processing".
        if self.processing or not text.strip():
            return False  # clear the buffer
        self._submit(text)
        return False  # clear the buffer

    def _submit(self, text: str) -> None:
        self.processing = True
        self._emit(f"\n> {text}\n")
        self.app.invalidate()
        threading.Thread(
            target=self._run_turn, args=(text,), name="tui-worker", daemon=True
        ).start()

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
        threading.Thread(
            target=self._ticker, name="tui-ticker", daemon=True
        ).start()

    def _ticker(self) -> None:
        # Advances ~2x/sec. If a turn ran on the UI thread this would stall, so a
        # moving tick is the visible proof the worker-thread boundary holds.
        import time as _time
        while not self._stop.is_set():
            _time.sleep(0.5)
            self.tick += 1
            if self.loop is not None:
                try:
                    self.loop.call_soon_threadsafe(self.app.invalidate)
                except Exception:
                    break

    def run(self) -> None:
        self.app.run(pre_run=self._on_start)


def run() -> None:
    MonitorTUI().run()


if __name__ == "__main__":
    run()
