from contextlib import contextmanager
import os
import sys
import threading
from typing import Iterator, Optional


@contextmanager
def progress_dots(message: Optional[str] = None, interval: float = 0.50) -> Iterator[None]:
    """Show periodic dots to indicate progress only on a TTY (or when forced).

    The function prints a `message` (if provided) and then prints a dot every
    `interval` seconds from a daemon thread until the context exits. By default,
    this indicator runs only when stderr is a TTY. To force progress output even
    when not a TTY, set the environment variable MONITOR_FORCE_PROGRESS to a
    non-empty value (e.g., "1").

    Args:
        message: Optional text printed once before starting dots.
        interval: Seconds between dots (default 0.50).

    Yields:
        None. Use in a with-statement to bound the progress indicator.

    Example:
        with progress_dots(\"Sending request\"):
            do_blocking_call()
    """
    # Prefer stderr for progress (so stdout can remain machine-friendly).
    force = bool(os.getenv("MONITOR_FORCE_PROGRESS"))
    is_terminal = sys.stderr.isatty()

    # If not a terminal and not forced, yield without starting thread.
    if not is_terminal and not force:
        if message:
            # Print message and newline so output stays neat in non-interactive logs.
            sys.stderr.write(f"{message}\n")
            sys.stderr.flush()
        yield
        return

    stop_event = threading.Event()
    printed_any = {"value": False}

    def _run() -> None:
        # Slight initial delay to avoid printing a dot for very short operations.
        if not stop_event.wait(interval):
            if not stop_event.is_set():
                sys.stderr.write(".")
                sys.stderr.flush()
                printed_any["value"] = True
        while not stop_event.wait(interval):
            sys.stderr.write(".")
            sys.stderr.flush()
            printed_any["value"] = True

    thread: Optional[threading.Thread] = None
    try:
        if message:
            sys.stderr.write(f"{message}")
            sys.stderr.flush()
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        yield
    finally:
        stop_event.set()
        if thread is not None:
            thread.join(timeout=2.0)
        # If we printed anything, finish the line.
        if printed_any["value"]:
            sys.stderr.write("\n")
            sys.stderr.flush()