"""Helpers for optional Monitor extras and clear install guidance.

Phase 2 keeps the default ``pip install .`` install lean. Specialized features
live behind extras declared in ``pyproject.toml``. Call ``require_extra`` (or
``import_optional``) at the point of use so missing packages fail locally with
an actionable install command instead of a raw ``ImportError``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Distribution name from pyproject.toml [project].name
DISTRIBUTION_NAME = "monitor_rdegraci2025"

# Maps extra name → packages users should expect that extra to provide.
EXTRA_PACKAGES: dict[str, tuple[str, ...]] = {
    "voice": ("openai-whisper", "pyaudio"),
    "tts": ("coqui-tts",),
    "chroma": ("chromadb",),
    "science": ("pandas", "scikit-learn", "joblib", "graphviz"),
    "database": ("duckdb",),
    "network": ("tavily-python",),
    "server": ("flask",),
    "aws": ("boto3",),
    "symbols": (
        "tree-sitter",
        "tree-sitter-python",
        "tree-sitter-javascript",
        "tree-sitter-typescript",
        "tree-sitter-go",
        "tree-sitter-rust",
        "tree-sitter-swift",
    ),
}

# Importable module name → extra that provides it.
MODULE_TO_EXTRA: dict[str, str] = {
    "whisper": "voice",
    "pyaudio": "voice",
    "TTS": "tts",
    "chromadb": "chroma",
    "pandas": "science",
    "sklearn": "science",
    "joblib": "science",
    "graphviz": "science",
    "duckdb": "database",
    "tavily": "network",
    "flask": "server",
    "boto3": "aws",
    "tree_sitter": "symbols",
    "tree_sitter_python": "symbols",
    "tree_sitter_javascript": "symbols",
    "tree_sitter_typescript": "symbols",
    "tree_sitter_go": "symbols",
    "tree_sitter_rust": "symbols",
    "tree_sitter_swift": "symbols",
}


class OptionalDependencyError(RuntimeError):
    """Raised when an optional extra is required but not installed."""


def install_command(extra: str) -> str:
    """Return the pip install command for one extra."""
    return f"pip install '{DISTRIBUTION_NAME}[{extra}]'"


def missing_extra_message(extra: str, *, feature: str | None = None) -> str:
    """Return a user-facing message for a missing optional extra.

    Args:
        extra: Extra name declared in ``pyproject.toml``.
        feature: Optional short feature label for context.
    """
    packages = EXTRA_PACKAGES.get(extra, ())
    package_bit = f" (provides {', '.join(packages)})" if packages else ""
    feature_bit = f" for {feature}" if feature else ""
    return (
        f"Missing optional dependency{feature_bit}. "
        f"Install the '{extra}' extra{package_bit} with: "
        f"{install_command(extra)}"
    )


def require_extra(extra: str, *, feature: str | None = None) -> None:
    """Raise ``OptionalDependencyError`` describing how to install ``extra``.

    Prefer calling this after a failed import so the message stays accurate.
    """
    raise OptionalDependencyError(missing_extra_message(extra, feature=feature))


def extra_for_module(module_name: str) -> str | None:
    """Return the extra that provides ``module_name``, if known."""
    root = module_name.split(".", 1)[0]
    return MODULE_TO_EXTRA.get(root)


def import_optional(module_name: str, *, feature: str | None = None) -> Any:
    """Import ``module_name`` or raise ``OptionalDependencyError``.

    Args:
        module_name: Dotted import path.
        feature: Optional short feature label for the error message.
    """
    try:
        return import_module(module_name)
    except Exception:
        extra = extra_for_module(module_name) or "all"
        require_extra(extra, feature=feature or module_name)


def load_optional(module_name: str) -> Any | None:
    """Import ``module_name`` and return ``None`` when unavailable."""
    try:
        return import_module(module_name)
    except Exception:
        return None
