"""Tests for MacroExpander in the Monitor OOP infrastructure layer."""
from __future__ import annotations

from monitor_oop.core.infrastructure.macro_expander import MacroExpander


def test_macro_expander_replaces_simple_macro() -> None:
    """Verify simple macro replacement works with the default delimiters."""

    expander = MacroExpander()
    result = expander.expand("Hello, {{name}}!", {"name": "world"})

    assert result == "Hello, world!"


def test_macro_expander_expands_nested_macros() -> None:
    """Verify nested macros are expanded recursively."""

    expander = MacroExpander()
    macros = {"name": "world", "greeting": "Hello, {{name}}!"}

    result = expander.expand("{{greeting}}", macros)

    assert result == "Hello, world!"


def test_macro_expander_leaves_unknown_macros_unchanged() -> None:
    """Verify unknown macros pass through unchanged."""

    expander = MacroExpander()

    assert expander.expand("{{missing}}", {}) == "{{missing}}"


def test_macro_expander_stops_after_max_depth() -> None:
    """Verify recursive expansion stops after the configured max depth."""

    expander = MacroExpander()
    macros = {"loop": "{{loop}}"}

    assert expander.expand("{{loop}}", macros, max_depth=2) == "{{loop}}"


def test_macro_expander_supports_custom_delimiters() -> None:
    """Verify custom delimiters can be used for expansion."""

    expander = MacroExpander(open_delimiter="<%", close_delimiter="%>")

    assert expander.expand("<%name%>", {"name": "world"}) == "world"
