"""Serialization helpers for LLM tool outputs and summarization follow-ups."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from monitor.lib.llm_model_utils import strip_openai_prefix

logger = logging.getLogger(__name__)

# ANSI escape sequences (SGR colors from e.g. `rg --pretty`, plus CSI/OSC forms).
# Terminal colors are for the USER; the LLM gains nothing from the escape codes
# but pays tokens for them (and they bloat the retained Responses chain + pollute
# logs). Stripped centrally at the two tool-result builders below so EVERY tool's
# output reaches the model clean while terminal prints stay colored.
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def strip_ansi(text):
    """Remove ANSI escape sequences from ``text`` (no-op for non-strings)."""
    if not isinstance(text, str) or "\x1b" not in text:
        return text
    return _ANSI_ESCAPE_RE.sub("", text)


def serialize_tool_output(result_or_error) -> str:
    """Serialize a tool result or error into a string.

    Args:
        result_or_error: The value returned by a tool or an exception.

    Returns:
        A stable string representation suitable for embedding in messages.
    """
    if result_or_error is None:
        return ""

    if isinstance(result_or_error, str):
        return result_or_error

    def _default(value):
        """Return a JSON-serializable fallback for unknown values."""
        try:
            if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
                return value.to_dict()
            if hasattr(value, "__dict__"):
                return {k: v for k, v in value.__dict__.items() if not k.startswith("_")}
            return repr(value)
        except Exception:
            return repr(value)

    try:
        return json.dumps(result_or_error, ensure_ascii=False, default=_default)
    except TypeError:
        try:
            if hasattr(result_or_error, "to_dict") and callable(
                getattr(result_or_error, "to_dict")
            ):
                return json.dumps(
                    result_or_error.to_dict(),
                    ensure_ascii=False,
                    default=_default,
                )
            if hasattr(result_or_error, "__dict__"):
                return json.dumps(
                    {
                        k: v
                        for k, v in result_or_error.__dict__.items()
                        if not k.startswith("_")
                    },
                    ensure_ascii=False,
                    default=_default,
                )
        except Exception:
            pass
    except Exception:
        pass

    try:
        return str(result_or_error)
    except Exception:
        return repr(result_or_error)


def build_function_call_output_item(
    call_id: str,
    result_or_error,
    serialized_output: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a standardized function call output item.

    Args:
        call_id: The identifier for the function or tool call.
        result_or_error: The function result or exception.
        serialized_output: Optional pre-serialized output string.

    Returns:
        A dictionary containing the serialized output and optional error
        metadata.
    """
    output_str = (
        serialized_output
        if serialized_output is not None
        else serialize_tool_output(result_or_error)
    )
    # Strip terminal color codes before the output reaches the model (Responses
    # path). See strip_ansi above.
    output_str = strip_ansi(output_str)
    item: Dict[str, Any] = {
        "call_id": call_id,
        "id": call_id,
        "output": output_str,
    }

    if isinstance(result_or_error, Exception):
        try:
            item["error"] = True
            item["error_type"] = type(result_or_error).__name__
            item["error_message"] = str(result_or_error)
        except Exception:
            logger.debug(
                "build_function_call_output_item: failed to attach error "
                "metadata",
                exc_info=True,
            )

    return item


def build_summarization_followup_params(
    prev_response_id: Optional[str],
    function_call_outputs: List[Dict[str, Any]],
    summary_instruction: str,
    model: str,
    max_output_tokens: int,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Construct parameters for a summarization follow-up request.

    Args:
        prev_response_id: Identifier of the previous response to reference.
        function_call_outputs: Tool call output items.
        summary_instruction: Instruction text guiding the summarization.
        model: The model name to use for summarization.
        max_output_tokens: Maximum tokens allowed in the summary output.
        tools: Optional tool descriptors.

    Returns:
        A parameter dictionary ready for a follow-up model call.
    """
    fc_outputs = function_call_outputs or []
    try:
        sanitized_outputs: List[Dict[str, Any]] = []
        for idx, item in enumerate(fc_outputs):
            if not isinstance(item, dict):
                logger.debug(
                    "build_summarization_followup_params: coercing non-dict "
                    "output at index %s",
                    idx,
                )
                try:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        coerced = {
                            "id": item[0],
                            "output": serialize_tool_output(item[1]),
                        }
                        sanitized_outputs.append(coerced)
                        continue
                except Exception:
                    pass
                sanitized_outputs.append(
                    {
                        "id": getattr(item, "id", f"item_{idx}"),
                        "output": serialize_tool_output(item),
                    }
                )
                continue
            sanitized_outputs.append(item)
    except Exception:
        logger.exception(
            "build_summarization_followup_params: failed to sanitize "
            "function_call_outputs; using originals"
        )
        sanitized_outputs = fc_outputs

    params: Dict[str, Any] = {
        "parent_response_id": prev_response_id,
        "summary_instruction": summary_instruction,
        "model": model,
        "max_output_tokens": (
            int(max_output_tokens) if max_output_tokens is not None else None
        ),
        "function_call_outputs": sanitized_outputs,
    }

    if tools:
        params["tools"] = tools

    try:
        params["_meta"] = {
            "source": "summarization_followup",
            "tool_count": len(sanitized_outputs),
            "model_normalized": (
                strip_openai_prefix(model) if isinstance(model, str) else model
            ),
        }
    except Exception:
        pass

    return params
