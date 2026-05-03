"""Macro expansion helpers for Monitor OOP."""

from __future__ import annotations

import logging
import re


logger = logging.getLogger(__name__)


class MacroExpander:
    """Expand macro references using recursive brace replacement."""

    def __init__(self, open_delimiter: str = "{{", close_delimiter: str = "}}") -> None:
        """Initialize the macro expander.

        Args:
            open_delimiter: Macro opening delimiter.
            close_delimiter: Macro closing delimiter.
        """
        self._open_delimiter = open_delimiter
        self._close_delimiter = close_delimiter
        self._pattern = re.compile(
            re.escape(open_delimiter) + r"\s*([^{}]+?)\s*" + re.escape(close_delimiter)
        )

    def expand(self, text: str, macros: dict[str, str], max_depth: int = 16) -> str:
        """Expand macro references in text.

        Args:
            text: Input text containing macro references.
            macros: Macro definitions to resolve.
            max_depth: Maximum recursive expansion depth.

        Returns:
            The expanded text.
        """
        logger.info("Starting macro expansion with max_depth=%s", max_depth)

        if max_depth <= 0:
            logger.info("Macro expansion terminated due to non-positive max_depth=%s", max_depth)
            logger.debug("Final expanded text: %s", text)
            return text

        expanded = self._expand_to_fixed_point(text, macros, max_depth)
        logger.debug("Final expanded text: %s", expanded)
        return expanded

    def _expand_to_fixed_point(self, text: str, macros: dict[str, str], max_depth: int) -> str:
        """Expand macros until a fixed point or depth limit is reached.

        Args:
            text: Input text containing macro references.
            macros: Macro definitions to resolve.
            max_depth: Maximum recursive expansion depth.

        Returns:
            The expanded text after iterative substitution.
        """
        expanded = text
        for depth in range(max_depth):
            next_expanded = self._expand_once(expanded, macros, max_depth - depth - 1)
            if next_expanded == expanded:
                logger.info("Macro expansion terminated after %s iteration(s)", depth + 1)
                break
            expanded = next_expanded
        else:
            logger.info("Macro expansion terminated after reaching max_depth=%s", max_depth)
        return expanded

    def _expand_once(self, text: str, macros: dict[str, str], max_depth: int) -> str:
        """Expand all macro references in a single pass.

        Args:
            text: Input text containing macro references.
            macros: Macro definitions to resolve.
            max_depth: Maximum recursive expansion depth remaining for nested values.

        Returns:
            The text after one substitution pass.
        """
        return self._pattern.sub(
            lambda match: self._replace_macro(match, macros, max_depth), text
        )

    def _resolve_macro_value(self, macro_value: str, macros: dict[str, str], max_depth: int) -> str:
        """Resolve nested macro references in a macro value.

        Args:
            macro_value: Macro value to expand.
            macros: Macro definitions to resolve.
            max_depth: Maximum recursive expansion depth remaining.

        Returns:
            The fully expanded macro value.
        """
        if max_depth <= 0:
            return macro_value
        return self._expand_to_fixed_point(macro_value, macros, max_depth)

    def _replace_macro(
        self, match: re.Match[str], macros: dict[str, str], max_depth: int
    ) -> str:
        """Replace a matched macro reference.

        Args:
            match: Regex match object for the macro reference.
            macros: Macro definitions to resolve.
            max_depth: Maximum recursive expansion depth remaining for nested values.

        Returns:
            The replacement text, or the original match for unknown macros.
        """
        macro_name = match.group(1)
        if macro_name not in macros:
            logger.debug("Unknown macro passthrough: %s", macro_name)
            return match.group(0)
        return self._resolve_macro_value(macros[macro_name], macros, max_depth)
