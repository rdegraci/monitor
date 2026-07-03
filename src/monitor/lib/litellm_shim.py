"""Fail-fast LiteLLM shim used to detect Ollama paths reaching LiteLLM."""

from __future__ import annotations

import traceback


def completion(*args, **kwargs):
    """Raise immediately when LiteLLM completion is invoked.

    Args:
        *args: Positional arguments forwarded by the caller.
        **kwargs: Keyword arguments forwarded by the caller.

    Raises:
        RuntimeError: Always raised to stop LiteLLM usage and capture a stack trace.
    """
    stack_trace = "".join(traceback.format_stack())
    raise RuntimeError(
        "Ollama requests must not use LiteLLM\n"
        f"args={args!r}\n"
        f"kwargs={kwargs!r}\n"
        f"stack_trace:\n{stack_trace}"
    )
