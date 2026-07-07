"""Responses-via-LiteLLM adapter for the isolated Monitor OOP application."""
from __future__ import annotations

import hashlib
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
        max_output_tokens: int | None = None,
    ) -> Any:
        """Call the OpenAI Responses API with the Responses-style model/input contract."""

        client = OpenAI(api_key=api_key)
        kwargs = self._build_request_kwargs(
            model=model,
            input=input,
            tools=tools,
            tool_choice=tool_choice,
            previous_response_id=previous_response_id,
            max_output_tokens=max_output_tokens,
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
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": input,
            "prompt_cache_key": self._build_prompt_cache_key(model, "turn"),
            "prompt_cache_retention": "24h",
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if previous_response_id is not None:
            kwargs["previous_response_id"] = previous_response_id
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        return kwargs

    def _build_prompt_cache_key(self, model: str, request_shape: str) -> str:
        """Build a stable prompt cache key for Responses API requests."""

        model_name = str(model or "unknown")
        shape = str(request_shape or "turn")
        model_token = model_name.replace("openai/", "")[:16]
        shape_token = shape[:12]
        cache_key = f"m:r:v1:m:{model_token}:q:{shape_token}"
        if len(cache_key) <= 64:
            return cache_key

        hash_input = f"{model_name}|{shape}".encode("utf-8")
        digest = hashlib.sha256(hash_input).hexdigest()[:16]
        return f"m:r:v1:h:{digest}"

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
