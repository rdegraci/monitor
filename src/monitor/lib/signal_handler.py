import signal
import logging
from monitor.lib.colors import yellow, reset

logger = logging.getLogger(__name__)

def signal_handler(sig, frame, msg="\nETX", use_colors=True):
    """
    Default SIGINT handler for clean CLI exit.

    Args:
        sig: Signal number
        frame: Current stack frame (from signal)
        msg (str): Message to print on exit
        use_colors (bool): Use color formatting in output
    """
    logger.info("SIGINT received, exiting...")
    if use_colors:
        print(f"{yellow}{msg}{reset}")
    else:
        print(msg)


def setup_sigint_handler(msg="\nETX", use_colors=True):
    """
    Register the default custom handler for SIGINT (Ctrl+C).

    Args:
        msg (str): Message to print on SIGINT
        use_colors (bool): Use color formatting in output
    """
    def handler(sig, frame):
        signal_handler(sig, frame, msg=msg, use_colors=use_colors)
    signal.signal(signal.SIGINT, handler)
