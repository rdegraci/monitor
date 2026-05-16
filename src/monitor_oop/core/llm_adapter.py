"""Responses-via-LiteLLM adapter for the isolated Monitor OOP application."""
from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI


logger = logging.getLogger(__name__)


class ResponsesOpenAiAdapter:
    """Responses-via-LiteLLM adapter behind a stable boundary.

    This adapter owns the Responses-style LiteLLM call path.
    """

    def complete(
        self,
        model: str,
        input: list[dict[str, str]] | Any,
        api_key: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        previous_response_id: str | None = None,
    ) -> Any:
        """Call the OpenAI Responses API with the Responses-style model/input contract."""

        client = OpenAI(api_key=api_key)
        kwargs = self._build_request_kwargs(
            model=model,
            input=input,
            tools=tools,
            tool_choice=tool_choice,
            previous_response_id=previous_response_id,
        )
        logger.info(
            "Calling OpenAI Responses with kwargs keys=%s previous_response_id_present=%s",
            list(kwargs.keys()),
            previous_response_id is not None,
        )
        return client.responses.create(**kwargs)

    def extract_text(self, response: Any) -> str:
        """Extract assistant text from a Responses API response object."""

        text = self._extract_output_text(response)
        if text:
            return text

        text = self._extract_output_items_text(response)
        if text:
            return text

        text = self._extract_legacy_choices_content(response)
        if text:
            return text

        text = self._extract_legacy_choices_text(response)
        if text:
            return text

        text = self._extract_response_text(response)
        if text:
            return text

        return ""

    def _build_request_kwargs(
        self,
        *,
        model: str,
        input: list[dict[str, str]] | Any,
        tools: list[dict[str, Any]] | None,
        tool_choice: Any | None,
        previous_response_id: str | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": input,
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if previous_response_id is not None:
            kwargs["previous_response_id"] = previous_response_id
        return kwargs

    def _extract_output_text(self, response: Any) -> str:
        try:
            content = response.output_text
            if content:
                return str(content).strip()
        except (AttributeError, TypeError):
            pass
        return ""

    def _extract_output_items_text(self, response: Any) -> str:
        try:
            output = response.output
            if output:
                parts: list[str] = []
                for item in output:
                    try:
                        item_type = getattr(item, "type", None)
                    except AttributeError:
                        item_type = None
                    try:
                        content = getattr(item, "content", None)
                    except AttributeError:
                        content = None
                    if content and item_type in {"message", "output_text"}:
                        if isinstance(content, list):
                            for content_item in content:
                                try:
                                    text = getattr(content_item, "text", None)
                                except AttributeError:
                                    text = None
                                if text:
                                    parts.append(str(text).strip())
                                    continue
                                try:
                                    text = content_item.get("text")  # type: ignore[union-attr]
                                except AttributeError:
                                    text = None
                                except TypeError:
                                    text = None
                                if text:
                                    parts.append(str(text).strip())
                        else:
                            parts.append(str(content).strip())
                text = "\n".join(part for part in parts if part)
                if text:
                    return text
        except (AttributeError, TypeError):
            pass
        return ""

    def _extract_legacy_choices_content(self, response: Any) -> str:
        try:
            content = response.choices[0].message.content
            if content:
                return str(content).strip()
        except (AttributeError, IndexError, TypeError):
            pass
        return ""

    def _extract_legacy_choices_text(self, response: Any) -> str:
        try:
            text = response.choices[0].message.text
            if text:
                return str(text).strip()
        except (AttributeError, IndexError, TypeError):
            pass
        return ""

    def _extract_response_text(self, response: Any) -> str:
        try:
            text = response.text
            if text:
                return str(text).strip()
        except (AttributeError, TypeError):
            pass
        return ""
