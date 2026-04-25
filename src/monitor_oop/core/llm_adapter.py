"""Responses-via-LiteLLM adapter for the isolated Monitor OOP application."""
from __future__ import annotations

from typing import Any

import litellm


class ResponsesLiteLLMAdapter:
    """Responses-via-LiteLLM adapter behind a stable boundary.

    This adapter owns the Responses-style LiteLLM call path.
    """

    def complete(self, model: str, messages: list[dict[str, str]], api_key: str) -> Any:
        """Call LiteLLM with the Responses-style model/messages contract."""

        return litellm.completion(model=model, messages=messages, api_key=api_key)

    def extract_text(self, response: Any) -> str:
        """Extract assistant text from a LiteLLM response object."""

        try:
            content = response.choices[0].message.content
            if content:
                return str(content).strip()
        except (AttributeError, IndexError, TypeError):
            pass
        try:
            output_text = response.output_text
            if output_text:
                return str(output_text).strip()
        except (AttributeError, TypeError):
            pass
        try:
            output = response.output
            if output:
                parts: list[str] = []
                for item in output:
                    try:
                        content = item.content
                    except AttributeError:
                        content = None
                    if content:
                        parts.append(str(content).strip())
                text = "\n".join(part for part in parts if part)
                if text:
                    return text
        except (AttributeError, TypeError):
            pass
        try:
            text = response.choices[0].message.text
            if text:
                return str(text).strip()
        except (AttributeError, IndexError, TypeError):
            pass
        try:
            text = response.text
            if text:
                return str(text).strip()
        except (AttributeError, TypeError):
            pass
        return ""
