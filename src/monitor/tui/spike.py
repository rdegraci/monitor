"""Spike: full-screen TUI proof-of-concept for `--tui`
(PLAN_MONITOR_TUI: P0 + P1 + thin P2). THROWAWAY — proves the two hard points
cheaply before the real phased build, using a STUB backend (not process_input):

- **P0**  a full-screen three-region layout: output window / info bar / input.
- **P1**  the (synchronous, blocking) backend runs in a WORKER THREAD; the UI
          never freezes — a live tick in the info bar keeps advancing while a
          slow 'turn' runs.
- **P2 (thin)**  the worker's rich/ANSI stdout is captured and rendered in the
          output window (the rich → ANSI → prompt_toolkit bridge in miniature).

Run via `monitor --tui` or `python -m monitor.tui.spike`.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import threading
import time

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.widgets import TextArea

# Simulated slow turn (the freeze test). Module-level so tests can zero it out.
_TURN_DELAY = 1.5


def _stub_backend(text: str) -> None:
    """Stand-in for the real (synchronous, blocking) process_input. Simulates a
    slow turn that prints rich-formatted output to stdout — exactly the shape of
    the real backend — so the spike exercises the stdout-capture + rich→ANSI path.
    """
    time.sleep(_TURN_DELAY)
    try:
        from rich.console import Console
        from rich.table import Table
        # color_system="standard" → simple 16-color SGR codes (e.g. \x1b[1;32m),
        # the most universally renderable by prompt_toolkit's ANSI() parser.
        c = Console(force_terminal=True, color_system="standard", width=80)

        c.print(f"[bold green]assistant[/]: you said [italic cyan]{text!r}[/] — "
                f"rendered via rich → ANSI → the output window.")
        c.print("[bold]colors:[/]  [red]red[/]  [green]green[/]  [yellow]yellow[/]  "
                "[blue]blue[/]  [magenta]magenta[/]  [cyan]cyan[/]")
        c.print("[bold]styles:[/]  [bold]bold[/]  [italic]italic[/]  "
                "[underline]underline[/]  [dim]dim[/]  [reverse]reverse[/]")

        table = Table(title="rich Table → output window", title_style="bold")
        table.add_column("field", style="cyan", no_wrap=True)
        table.add_column("value", style="green")
        table.add_row("status", "ok")
        table.add_row("model", "openai/gpt-5.4-mini")
        table.add_row("agents", "[yellow]1 running[/]")
        c.print(table)
    except Exception:
        print(f"assistant: you said {text!r}")


def _run_and_capture(text: str) -> str:
    """Run the stub backend with stdout redirected; return the captured (ANSI)
    text. The P2 bridge in miniature — testable headlessly (no TTY)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _stub_backend(text)
    return buf.getvalue()


class SpikeApp:
    def __init__(self):
        self._chunks = [
            "(spike) Type a line and press Enter. Watch the tick in the info bar "
            "keep moving during the ~1.5s 'turn' — that proves the UI isn't frozen "
            "while the backend runs on a worker thread.\n"
        ]
        self.processing = False
        self.tick = 0
        self.loop = None
        self._stop = threading.Event()

        self.input = TextArea(
            height=1,
            multiline=False,
            prompt="monitor (spike) ]] ",
            accept_handler=self._on_accept,
        )
        body = HSplit([
            Window(FormattedTextControl(self._output_text), wrap_lines=True),
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
            # Pin a real color depth so the ANSI() output actually renders in
            # color (default detection was clamping it to monochrome).
            color_depth=ColorDepth.DEPTH_8_BIT,
        )

    # --- region content -----------------------------------------------------

    def _output_text(self):
        return ANSI("".join(self._chunks))

    def _info_text(self):
        state = "WORKING…" if self.processing else "idle"
        return (
            f" tick {self.tick}    {state}\n"
            f" agents — (none in spike)    ~T:$0.00  C:0 (0%)    (info bar demo)"
        )

    def _append(self, s: str) -> None:
        self._chunks.append(s)

    # --- input → worker-thread turn (P1) ------------------------------------

    def _on_accept(self, buff):
        text = buff.text
        if text.strip():
            self._append(f"\n> {text}\n")
            self._submit(text)
        return False  # clear the input buffer

    def _submit(self, text: str) -> None:
        self.processing = True
        self.app.invalidate()

        def work():
            captured = _run_and_capture(text)  # blocking — OFF the UI thread

            def done():
                self._append(captured)
                self.processing = False
                self.app.invalidate()

            if self.loop is not None:
                self.loop.call_soon_threadsafe(done)

        threading.Thread(target=work, name="spike-worker", daemon=True).start()

    # --- lifecycle ----------------------------------------------------------

    def _on_start(self) -> None:
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.get_event_loop()
        threading.Thread(target=self._ticker, name="spike-ticker", daemon=True).start()

    def _ticker(self) -> None:
        # Advances ~4x/sec. If the worker ran on the UI thread, this would stall
        # during a turn — so a moving tick proves the boundary holds.
        while not self._stop.is_set():
            time.sleep(0.25)
            self.tick += 1
            if self.loop is not None:
                try:
                    self.loop.call_soon_threadsafe(self.app.invalidate)
                except Exception:
                    break

    def run(self) -> None:
        self.app.run(pre_run=self._on_start)


def run() -> None:
    SpikeApp().run()


if __name__ == "__main__":
    run()
