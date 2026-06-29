"""External and integration helper commands for built-in command dispatch."""

import logging
from typing import Any

from monitor import config
from monitor.lib.external_services import (
    send_linkedin_message,
    send_twitch_message_command,
)
from monitor.lib.summarizers import (
    summarize_conversation_for_linkedin,
    summarize_conversation_for_twitch,
)

logger = logging.getLogger(__name__)


def deploy_model_command(args: dict[str, Any]) -> Any:
    """Deploy the specified model to an endpoint.

    Args:
        args: Deployment settings including model path, endpoint URL, and
            deployment platform.

    Returns:
        Deployment result on success, or an error string on failure.
    """
    from monitor.lib.deployment import deploy_model

    model_path = args.get("model_path")
    endpoint_url = args.get("endpoint_url")
    deployment_platform = args.get("deployment_platform")
    try:
        return deploy_model(model_path, endpoint_url, deployment_platform)
    except Exception as exc:
        logger.error("Error in deploy_model_command: %s", exc, exc_info=True)
        return f"Error deploying model: {exc}"


def monitor_model_performance_command(args: dict[str, Any]) -> Any:
    """Monitor the performance of a deployed model.

    Args:
        args: Monitoring settings including endpoint URL and metrics to track.

    Returns:
        Monitoring result on success, or an error string on failure.
    """
    from monitor.lib.deployment import monitor_model_performance

    endpoint_url = args.get("endpoint_url")
    metrics_to_track = args.get("metrics_to_track", [])
    try:
        return monitor_model_performance(endpoint_url, metrics_to_track)
    except Exception as exc:
        logger.error(
            "Error in monitor_model_performance_command: %s",
            exc,
            exc_info=True,
        )
        return f"Error monitoring model performance: {exc}"


def twitch_summary_command(arg: Any | None = None) -> None:
    """Summarize the conversation history for Twitch broadcasting.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg
    try:
        summary = summarize_conversation_for_twitch(
            config.CONVERSATION_HISTORY,
            config.MODEL,
        )
        if not summary:
            return
        print(summary)
        send_twitch_message_command(summary)
    except Exception as exc:
        logger.error(
            "Failed to summarize conversation for Twitch: %s",
            exc,
            exc_info=True,
        )


def linkedin_summary_command(arg: Any | None = None) -> None:
    """Summarize the conversation history for LinkedIn broadcasting.

    Args:
        arg: Ignored dispatcher argument.

    Returns:
        None.
    """
    del arg
    try:
        summary = summarize_conversation_for_linkedin(
            config.CONVERSATION_HISTORY,
            config.MODEL,
        )
        if not summary:
            return
        print(summary)
        if send_linkedin_message is not None:
            send_linkedin_message(summary)
    except Exception as exc:
        logger.error(
            "Failed to summarize conversation for LinkedIn: %s",
            exc,
            exc_info=True,
        )
