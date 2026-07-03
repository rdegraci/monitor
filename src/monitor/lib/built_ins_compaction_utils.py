"""Compaction helper commands for built-in command dispatch."""

import logging

import monitor.lib.llm_utils as llm_utils
import litellm

from monitor import config
from monitor.lib.display_output import print_colored_error

logger = logging.getLogger(__name__)


def _resolve_compact_command_dependencies():
    """Resolve active dependencies, preferring built_in_commands when available."""
    active_config = config
    active_logger = logger
    active_print = print
    active_print_colored_error = print_colored_error
    active_build_system_prompt = None
    active_find_compaction_split_index = None

    try:
        from monitor.lib import built_in_commands as built_in_commands_module

        active_config = getattr(built_in_commands_module, "config", active_config)
        active_logger = getattr(built_in_commands_module, "logger", active_logger)
        active_print = getattr(built_in_commands_module, "print", active_print)
        active_print_colored_error = getattr(
            built_in_commands_module,
            "print_colored_error",
            active_print_colored_error,
        )
        active_build_system_prompt = getattr(
            built_in_commands_module,
            "build_system_prompt",
            active_build_system_prompt,
        )
        active_find_compaction_split_index = getattr(
            built_in_commands_module,
            "_find_compaction_split_index",
            active_find_compaction_split_index,
        )
    except Exception:
        pass

    return (
        active_config,
        active_logger,
        active_print,
        active_print_colored_error,
        active_build_system_prompt,
        active_find_compaction_split_index,
    )


def compact_command(arg: str | None = None) -> None:
    """Manually run the same partial-preserve compaction flow used automatically.

    Args:
        arg: Optional argument string. This command does not accept arguments.

    Returns:
        None.
    """
    (
        active_config,
        active_logger,
        active_print,
        active_print_colored_error,
        active_build_system_prompt,
        active_find_compaction_split_index,
    ) = _resolve_compact_command_dependencies()

    if arg is not None and str(arg).strip():
        active_print_colored_error(":compact does not accept arguments.")
        return

    try:
        from monitor.lib import rate_limiter
        from monitor.lib.history import (
            _find_compaction_split_index,
            generate_conversation_summary,
            reset_conversation_with_partial_summary,
        )
        from monitor.lib.system_prompt import build_system_prompt
        from monitor.lib.token_management import count_message_tokens

        find_compaction_split_index = (
            active_find_compaction_split_index or _find_compaction_split_index
        )
        build_system_prompt_func = (
            active_build_system_prompt or build_system_prompt
        )

        history = getattr(active_config, "CONVERSATION_HISTORY", None) or []
        keep_turns = getattr(active_config, "RECENT_TURNS_PRESERVED_ON_COMPACT", 6)
        split_idx = find_compaction_split_index(history, keep_turns)
        if split_idx is None:
            active_print("Not enough history to compact yet.")
            active_logger.info(
                "Manual compaction skipped: history has <= %s user turns.",
                keep_turns,
            )
            return

        old_portion = list(history[:split_idx])
        preserved = list(history[split_idx:])
        system_prompt = build_system_prompt_func(
            session_id=getattr(active_config, "SESSION_ID", None)
        )
        summary_response = generate_conversation_summary(
            system_prompt,
            old_portion,
            active_config.SUMMARIZATION_CONFIG,
            active_config.MODEL,
            llm_utils.call_litellm_completion,
            count_message_tokens,
            rate_limiter.RATE_LIMITER,
            active_logger,
            active_config,
        )

        summary_content = None
        try:
            if (
                hasattr(summary_response, "choices")
                and summary_response.choices
                and len(summary_response.choices) > 0
                and hasattr(summary_response.choices[0], "message")
                and summary_response.choices[0].message is not None
                and hasattr(summary_response.choices[0].message, "content")
            ):
                summary_content = summary_response.choices[0].message.content
        except Exception:
            active_logger.exception(
                "Failed to extract summary content from manual compaction response."
            )

        reset_conversation_with_partial_summary(
            summary_content or "",
            system_prompt,
            preserved,
            active_config.CONVERSATION_HISTORY,
            active_logger,
            active_config,
        )
        active_config.SESSION_COMPACTION_COUNT = (
            getattr(active_config, "SESSION_COMPACTION_COUNT", 0) + 1
        )
        active_print("Conversation compacted.")
        active_logger.info(
            "Manual compaction complete: preserved %s recent message(s).",
            len(preserved),
        )
    except Exception as exc:
        active_logger.error("Manual compaction failed: %s", exc, exc_info=True)
        active_print_colored_error(f"Manual compaction failed: {exc}")


def compact_history_command(
    arg,
    config_module,
    print_func,
    color_warning_funcs,
    logger_obj,
):
    """Adjust the configured conversation history size.

    Args:
        arg: Integer argument string for the new size.
        config_module: Config module-like object containing history settings.
        print_func: Print-like callable used for user-facing output.
        color_warning_funcs: Warning printer(s) passed to history adjustment.
        logger_obj: Logger used by the adjustment routine.

    Returns:
        None.
    """
    try:
        new_size = int(arg)
        from monitor.lib.history import adjust_history_size

        result = adjust_history_size(
            new_size,
            config_module.CONVERSATION_HISTORY,
            config_module.CONVERSATION_MAX_SIZE,
            print_func,
            color_warning_funcs,
            logger_obj,
        )
        config_module.CONVERSATION_MAX_SIZE = result
    except Exception as exc:
        print_func(f"Error: {exc}")
