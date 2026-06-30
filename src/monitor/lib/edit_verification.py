"""Tiered, pre-write verification of edited file content.

A shared gate used by deterministic edit tools (e.g. ``bulk_replace_in_files``)
and intended for reuse by the ``modify_source_code`` hardening work. Given the
*resulting* content for a path, it answers "is this still valid?" before the
edit is allowed to touch disk.

Three tiers, keyed by file extension:

- **code** — parse/compile check. Python ``ast.parse`` (no execution); Swift
  ``swiftc -parse`` (parse only, no build) when a toolchain is present.
- **structured text** — structural parse. ``.json`` / ``.yaml`` / ``.toml`` /
  ``.xml``. A careless edit can silently turn valid JSON invalid; this catches
  it before the write.
- **freeform text** — ``.md`` / ``.txt`` / logs / unknown extensions. Nothing
  to validate; skip.

Guiding rule: **degrade to a logged skip, never hard-block.** If a validator's
dependency is missing (PyYAML not installed), its toolchain is absent (no
``swiftc`` on PATH), or the validator itself errors unexpectedly, the gate
returns OK with tier ``"skip"`` rather than blocking an otherwise-fine edit.

Swift note: ``swiftc -parse`` runs only the parser, so it reports *syntax*
errors, not missing-symbol/missing-import errors (those need ``-typecheck`` +
the full module). That makes a single-file syntax gate safe — but if ``swiftc``
is unavailable, verification skips rather than blocks.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:  # py3.11+
    import tomllib  # type: ignore
except Exception:  # pragma: no cover - depends on interpreter version
    tomllib = None  # type: ignore

try:
    from monitor._stubs import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore

# Tier classification by extension (lowercase).
CODE_EXTS = {".py", ".swift"}
STRUCTURED_EXTS = {".json", ".yaml", ".yml", ".toml", ".xml"}

SWIFT_PARSE_TIMEOUT = 30  # seconds


def classify(path: str) -> str:
    """Return the verification tier for a path: 'code' | 'structured' | 'freeform'."""
    ext = os.path.splitext(path)[1].lower()
    if ext in CODE_EXTS:
        return "code"
    if ext in STRUCTURED_EXTS:
        return "structured"
    return "freeform"


def verify_file_content(path: str, content: str) -> Tuple[bool, Optional[str], str]:
    """Validate ``content`` as the future contents of ``path``.

    Returns ``(ok, error_message, tier)``:
    - ``(True, None, tier)`` — valid (or intentionally skipped).
    - ``(False, "<reason>", tier)`` — content is invalid for its type; the
      caller must NOT write it.

    ``tier`` is one of ``"code"``, ``"structured"``, ``"freeform"``, ``"skip"``.
    Never raises for a content problem — a malformed file is a clean
    ``(False, ...)``; an *infrastructure* problem (missing dep/toolchain) is a
    ``(True, None, "skip")`` with a log line.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".py":
        try:
            ast.parse(content)
            return True, None, "code"
        except SyntaxError as e:
            return False, f"Python syntax error: {e}", "code"

    if ext == ".swift":
        return _verify_swift(content)

    if ext == ".json":
        try:
            json.loads(content)
            return True, None, "structured"
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}", "structured"

    if ext in (".yaml", ".yml"):
        if yaml is None:
            logger.info("PyYAML not installed; skipping YAML verification for %s", path)
            return True, None, "skip"
        try:
            yaml.safe_load(content)
            return True, None, "structured"
        except yaml.YAMLError as e:  # type: ignore[attr-defined]
            return False, f"Invalid YAML: {e}", "structured"

    if ext == ".toml":
        if tomllib is None:
            logger.info("tomllib unavailable; skipping TOML verification for %s", path)
            return True, None, "skip"
        try:
            tomllib.loads(content)
            return True, None, "structured"
        except tomllib.TOMLDecodeError as e:  # type: ignore[attr-defined]
            return False, f"Invalid TOML: {e}", "structured"

    if ext == ".xml":
        try:
            ET.fromstring(content)
            return True, None, "structured"
        except ET.ParseError as e:
            return False, f"Invalid XML: {e}", "structured"

    # Freeform text / unknown extension: nothing to validate.
    return True, None, "freeform"


def _verify_swift(content: str) -> Tuple[bool, Optional[str], str]:
    swiftc = shutil.which("swiftc")
    if not swiftc:
        logger.info("swiftc not on PATH; skipping Swift verification")
        return True, None, "skip"

    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".swift")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        proc = subprocess.run(
            [swiftc, "-parse", tmp],
            capture_output=True,
            text=True,
            timeout=SWIFT_PARSE_TIMEOUT,
        )
        if proc.returncode != 0:
            return False, f"Swift parse error: {proc.stderr.strip()[:500]}", "code"
        return True, None, "code"
    except (subprocess.TimeoutExpired, OSError) as e:
        # Toolchain present but unusable — degrade to skip, never hard-block.
        logger.warning("swiftc verification could not run (%s); skipping", e)
        return True, None, "skip"
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
