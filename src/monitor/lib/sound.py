"""Simple cross-platform sound/notification helpers.

This module provides a tiny utility to ring the terminal bell (or an OS-level
beep where available) to notify the user that a task has completed.

The helper prefers prompt_toolkit's bell when running inside the interactive
application. It falls back to platform-native mechanisms (winsound on Windows),
then to the ASCII BEL character on stdout, which many terminals interpret as a
bell.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def ring_bell(enabled: bool = True) -> bool:
    """Ring the terminal/OS bell to notify the user.

    The function attempts several strategies in order of preference:
    1) If prompt_toolkit is active, use the application's output.bell().
    2) On Windows, use winsound.MessageBeep.
    3) Fallback to printing the ASCII BEL ("\a").

    Args:
        enabled (bool): When False, do nothing and return False.

    Returns:
        bool: True if a bell/beep attempt was made, False if disabled.
    """

    if not enabled:
        logger.debug("ring_bell: disabled -> no-op")
        return False

    # 1) Try prompt_toolkit, if available and an app is running.
    try:
        from prompt_toolkit.application.current import get_app  # type: ignore

        try:
            app = get_app()
            # Some environments may not have a real output; guard defensively.
            output = getattr(app, "output", None)
            if output and hasattr(output, "bell"):
                output.bell()
                logger.debug("ring_bell: used prompt_toolkit output.bell()")
                return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("ring_bell: prompt_toolkit bell failed: %s", exc)
    except Exception:
        # prompt_toolkit not installed or not available in this context.
        pass

    # 2) Windows-specific bell
    if sys.platform.startswith("win"):
        try:
            import winsound  # type: ignore

            winsound.MessageBeep(getattr(winsound, "MB_OK", -1))
            logger.debug("ring_bell: used winsound.MessageBeep")
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("ring_bell: winsound failed: %s", exc)

    # 3) Fallback: ASCII BEL on stdout
    try:
        print("\a", end="", flush=True)
        logger.debug("ring_bell: printed ASCII BEL to stdout")
        return True
    except Exception as exc:  # pragma: no cover - extremely unlikely
        logger.debug("ring_bell: printing BEL failed: %s", exc)
        return False
