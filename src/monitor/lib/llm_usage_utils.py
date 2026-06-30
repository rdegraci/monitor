"""Token usage and truncation helpers for LLM integrations."""

import logging
from typing import Any, Optional, Tuple, Union

from monitor import config

try:
    from monitor.lib import rate_limiter as rate_limiter_module
except Exception:
    rate_limiter = None
else:
    rate_limiter = rate_limiter_module

logger = logging.getLogger(__name__)


def safe_extract_total_tokens(usage: Any) -> Optional[int]:
    """Safely extract a canonical total token count from a usage-like object.

    Args:
        usage: The usage value as a dict, object, number, or string.

    Returns:
        The extracted total token count, or None when ``usage`` is None.

    Raises:
        ValueError: If the input cannot be coerced into a token count.
    """
    if usage is None:
        return None

    if isinstance(usage, int):
        return max(0, usage)
    if isinstance(usage, float):
        try:
            return max(0, int(usage))
        except Exception:
            return max(0, int(float(usage)))

    if isinstance(usage, str):
        usage_str = usage.strip()
        if usage_str == "":
            raise ValueError("Empty string provided for usage")
        try:
            return max(0, int(usage_str))
        except Exception:
            try:
                return max(0, int(float(usage_str)))
            except Exception as error:
                raise ValueError(
                    f"Unable to parse numeric string for usage: {usage!r}"
                ) from error

    if isinstance(usage, dict):
        preferred = ("total_tokens", "total", "total_used", "usage", "tokens")
        for key in preferred:
            if key in usage and usage.get(key) is not None:
                return safe_extract_total_tokens(usage.get(key))
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            try:
                prompt = usage.get("prompt_tokens", 0) or 0
                completion = usage.get("completion_tokens", 0) or 0
                return max(0, int(prompt) + int(completion))
            except Exception:
                pass
        raise ValueError(f"Unable to coerce total tokens from usage dict: {usage!r}")

    attr_candidates = (
        "total_tokens",
        "total",
        "total_used",
        "usage",
        "tokens",
        "prompt_tokens",
        "completion_tokens",
    )
    for attr in attr_candidates:
        if hasattr(usage, attr):
            try:
                return safe_extract_total_tokens(getattr(usage, attr))
            except Exception:
                continue

    if hasattr(usage, "__dict__"):
        try:
            return safe_extract_total_tokens({k: v for k, v in usage.__dict__.items()})
        except Exception:
            pass

    raise ValueError(f"Unable to coerce total tokens from usage: {usage!r}")


def compute_token_delta(
    current_total: Optional[Union[int, float]],
    previous_total: Optional[Union[int, float]],
) -> int:
    """Compute a safe, non-negative delta between two token totals.

    Args:
        current_total: The current canonical total token count.
        previous_total: The previous total token count.

    Returns:
        A non-negative integer delta representing additional tokens used.
    """
    if current_total is None:
        return 0
    try:
        current = int(current_total)
    except Exception:
        try:
            current = int(float(current_total))
        except Exception:
            logger.debug(
                "compute_token_delta: unable to coerce current_total=%r",
                current_total,
            )
            return 0

    if previous_total is None:
        return max(0, current)

    try:
        prev = int(previous_total)
    except Exception:
        try:
            prev = int(float(previous_total))
        except Exception:
            logger.debug(
                "compute_token_delta: unable to coerce previous_total=%r",
                previous_total,
            )
            prev = 0

    return max(0, current - prev)


def apply_usage_delta(
    usage: Any,
    previous_total: Optional[Union[int, float]] = None,
) -> Tuple[Optional[int], int]:
    """Apply a usage update by computing a delta and updating token counters.

    Args:
        usage: The usage payload as a dict, object, number, or string.
        previous_total: Optional previous total count to compute a delta against.

    Returns:
        A tuple of ``(current_total_or_none, delta_int)``.

    Raises:
        ValueError: If ``usage`` cannot be coerced to a token count.
    """
    try:
        current = safe_extract_total_tokens(usage)
    except ValueError:
        logger.debug(
            "apply_usage_delta: could not extract total tokens from usage; "
            "skipping updates."
        )
        raise

    delta = compute_token_delta(current, previous_total)

    if delta > 0:
        try:
            from monitor.lib import token_management

            token_management.update_token_usage(delta)
        except Exception:
            logger.exception("apply_usage_delta: update_token_usage failed")

        if rate_limiter is not None:
            candidate_names = (
                "add_usage",
                "add_tokens",
                "consume",
                "consume_tokens",
                "record_usage",
                "record",
            )
            for name in candidate_names:
                fn = getattr(rate_limiter, name, None)
                if callable(fn):
                    try:
                        fn(delta)
                        break
                    except Exception:
                        logger.debug(
                            "apply_usage_delta: rate_limiter.%s failed",
                            name,
                            exc_info=True,
                        )

    try:
        if delta > 0:
            setattr(config, "CANONICAL_TOKEN_USAGE", current)
    except Exception:
        logger.debug(
            "apply_usage_delta: unable to set config.CANONICAL_TOKEN_USAGE",
            exc_info=True,
        )

    return current, delta


def truncate_to_token_limit(
    text: str,
    token_limit: int,
    model: Optional[str] = None,
) -> str:
    """Truncate text to a given token limit.

    Args:
        text: The input text to truncate.
        token_limit: Maximum allowed token count.
        model: Optional model name used to choose a tiktoken encoding.

    Returns:
        The original text when it fits within the token limit, or a truncated
        string ending with a sentinel marker.
    """
    sentinel = f"...[TRUNCATED to token limit {token_limit}]"
    try:
        if text is None:
            return ""
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                return ""
        try:
            tok_limit = int(token_limit)
        except Exception:
            tok_limit = 0

        if tok_limit <= 0:
            return sentinel

        try:
            import tiktoken  # type: ignore

            encoding = None
            if model and hasattr(tiktoken, "encoding_for_model"):
                try:
                    encoding = tiktoken.encoding_for_model(model)
                except Exception:
                    encoding = None
            if encoding is None:
                try:
                    encoding = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    encoding = None

            if encoding is not None:
                try:
                    tokens = encoding.encode(text)
                    if len(tokens) <= tok_limit:
                        return text
                    logger.warning(
                        "Truncating text to token limit %s for model %s "
                        "(original tokens=%s)",
                        tok_limit,
                        model,
                        len(tokens),
                    )
                    take = max(0, tok_limit - 3)
                    truncated_tokens = tokens[:take]
                    try:
                        decoded = encoding.decode(truncated_tokens)
                        return decoded + sentinel
                    except Exception:
                        try:
                            partial_text = "".join(
                                chr(token % 0x110000)
                                for token in truncated_tokens[
                                    : max(0, min(len(truncated_tokens), 1000))
                                ]
                            )
                            return partial_text + sentinel
                        except Exception:
                            return sentinel
                except Exception:
                    pass
        except Exception:
            pass

        avg_chars_per_token = 4
        char_limit = tok_limit * avg_chars_per_token
        if len(text) <= char_limit:
            return text
        logger.warning(
            "Truncating text with character fallback to token limit %s for "
            "model %s (original chars=%s, approx char limit=%s)",
            tok_limit,
            model,
            len(text),
            char_limit,
        )
        take_chars = max(0, char_limit - len(sentinel))
        return text[:take_chars] + sentinel
    except Exception as error:
        logger.exception("truncate_to_token_limit failed: %s", error)
        try:
            txt = "" if text is None else str(text)
            return txt[: max(0, token_limit * 4)] + sentinel if txt else ""
        except Exception:
            return ""
