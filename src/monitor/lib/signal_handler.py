import signal
import logging
from monitor.lib.colors import yellow, reset
import contextlib

logger = logging.getLogger(__name__)

def signal_handler(sig, frame, msg="\nETX", use_colors=True):
    """Default SIGINT handler for clean CLI exit.

    Args:
        sig (int): Signal number.
        frame: Current stack frame (from signal).
        msg (str): Message to print on exit. Defaults to "\\nETX".
        use_colors (bool): Use color formatting in output. Defaults to True.
    """
    logger.info("SIGINT received, exiting...")
    if use_colors:
        print(f"{yellow}{msg}{reset}")
    else:
        print(msg)


def setup_sigint_handler(msg="\nETX", use_colors=True):
    """Register the default custom handler for SIGINT (Ctrl+C).

    Args:
        msg (str): Message to print on SIGINT. Defaults to "\\nETX".
        use_colors (bool): Use color formatting in output. Defaults to True.
    """
    def handler(sig, frame):
        signal_handler(sig, frame, msg=msg, use_colors=use_colors)
    signal.signal(signal.SIGINT, handler)


@contextlib.contextmanager
def temporary_default_sigint():
    """Temporarily set SIGINT to the default KeyboardInterrupt behavior.

    During the scope of this context manager, SIGINT (Ctrl+C) triggers the
    default signal handler, which raises KeyboardInterrupt. Upon exit, the
    previous SIGINT handler is restored.

    Yields:
        None: Code within the context runs with default SIGINT behavior.

    Raises:
        KeyboardInterrupt: If SIGINT is received while inside the context.
    """
    previous = signal.getsignal(signal.SIGINT)
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        yield
    finally:
        try:
            signal.signal(signal.SIGINT, previous)
        except Exception:
            logger.exception("Failed to restore previous SIGINT handler")
