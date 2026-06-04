"""Shared safety guards for tool dispatchers.

Right now this is just the write-size cap (companion to the existing
read-side LARGE_FILE_TOKEN_THRESHOLD in core/tooling.py). Lives in its
own module because the check is invoked from multiple write tools across
lib/os.py and lib/text_file_editor.py — a free function in a shared
module is cleaner than duplicating the same five lines four times.

Future siblings (max output bytes, path sandbox, etc.) belong here too.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from monitor import config

logger = logging.getLogger(__name__)


def check_write_size(content: Optional[str], tool_label: str) -> Tuple[bool, Optional[str]]:
    """Validate a write payload against config.MAX_FILE_WRITE_BYTES.

    Returns ``(ok, error_message)``:

    - ``(True, None)`` — payload is under cap (or cap is disabled), proceed.
    - ``(False, "...")`` — payload exceeds the cap. The caller should surface
      the error to the model as the tool result, not raise — a raise would
      orphan the assistant's tool_call entry in history and trip the
      provider-rejects-orphan-tool-calls failure mode.

    The cap is on **UTF-8-encoded byte length**, not character count: a
    string with a few emojis is bigger on disk than ``len(s)`` suggests.
    Reading `config.MAX_FILE_WRITE_BYTES` at call time (not import time)
    lets tests monkeypatch the value and lets runtime config reloads
    take effect without re-importing this module.
    """
    cap = getattr(config, "MAX_FILE_WRITE_BYTES", 0) or 0
    if cap <= 0:
        # 0 (or unset) disables the cap entirely — preserves prior behavior
        # for anyone explicitly opting out.
        return True, None
    if content is None:
        return True, None
    try:
        size = len(content.encode("utf-8"))
    except (AttributeError, UnicodeEncodeError) as e:
        # If the content isn't a str (or has surrogate-pair issues),
        # fall back to len() — character count is a reasonable proxy
        # and we'd rather guess high than skip the check.
        logger.debug("check_write_size: encode fallback for %s: %s", tool_label, e)
        try:
            size = len(content)
        except TypeError:
            return True, None  # non-sized content; can't enforce a cap
    if size <= cap:
        return True, None
    return False, (
        f"{tool_label}: write rejected — payload size {size} bytes exceeds "
        f"MAX_FILE_WRITE_BYTES={cap}. Reduce the content size, split the write "
        f"across multiple smaller files, or raise the cap in config.yaml if "
        f"this write is legitimate."
    )
