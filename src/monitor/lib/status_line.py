"""Status-line modes and session hygiene notices (PLAN Phase 6).

Three display modes control how much telemetry appears in the REPL prompt and
TUI info bar (both read :func:`monitor.core.conversation.compute_prompt_display`):

- ``minimal`` — ``H:`` message count + ``C:`` cliff proximity only
- ``coding``  — ``H: C: U: F:`` (recommended default)
- ``debug``   — full gauges including ``R:``, ``L:``, ``RT:``, cache mix line
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Sequence, Tuple

from monitor import config

logger = logging.getLogger(__name__)

VALID_STATUS_LINE_MODES: Tuple[str, ...] = ("minimal", "coding", "debug")
DEFAULT_STATUS_LINE_MODE = "coding"

# Warn once per cliff-streak level at or above this threshold.
CLIFF_STREAK_WARN_THRESHOLD = 3

_RECOVERY_HINT = (
    "Recovery: :break_chain (keep history, drop 2x cliff) · "
    ":compact (summarize older turns) · :reset_history (fresh task)"
)

_LAST_CLIFF_WARNING_AT = 0


def normalize_status_line_mode(value: Optional[str]) -> str:
    """Return a validated mode name, falling back to the default."""
    if not isinstance(value, str):
        return DEFAULT_STATUS_LINE_MODE
    mode = value.strip().lower()
    if mode in VALID_STATUS_LINE_MODES:
        return mode
    return DEFAULT_STATUS_LINE_MODE


def get_status_line_mode() -> str:
    """Return the active status-line mode from runtime config."""
    return normalize_status_line_mode(getattr(config, "STATUS_LINE_MODE", DEFAULT_STATUS_LINE_MODE))


def set_status_line_mode(mode: str) -> str:
    """Set and return the validated status-line mode."""
    resolved = normalize_status_line_mode(mode)
    config.STATUS_LINE_MODE = resolved
    return resolved


def status_cache_line_enabled(mode: Optional[str] = None) -> bool:
    """Return True when the cache-composition second line should render."""
    return normalize_status_line_mode(mode or get_status_line_mode()) == "debug"


def _allowed_labels(mode: str) -> frozenset[str]:
    if mode == "minimal":
        return frozenset({"H", "C"})
    if mode == "coding":
        return frozenset({"H", "C", "U", "F"})
    return frozenset({"F", "C", "R", "U", "L", "H", "RT"})


def _segment_order(mode: str) -> Tuple[str, ...]:
    if mode == "minimal":
        return ("H", "C")
    if mode == "coding":
        return ("H", "C", "U", "F")
    return ("F", "C", "R", "U", "L", "H", "RT")


def filter_status_segments(
    segments: Sequence[Tuple[str, str]],
    mode: Optional[str] = None,
) -> List[str]:
    """Filter rendered ``Label:value`` segments for the active mode.

    Args:
        segments: Ordered ``(label, rendered_value)`` pairs such as
            ``("F", "<colored>…")``. Empty values are skipped.
        mode: Optional override; defaults to the live config mode.

    Returns:
        List of strings like ``F:<value>`` suitable for joining.
    """
    resolved = normalize_status_line_mode(mode or get_status_line_mode())
    allowed = _allowed_labels(resolved)
    by_label = {
        label: value
        for label, value in segments
        if value and label in allowed
    }
    return [f"{label}:{by_label[label]}" for label in _segment_order(resolved) if label in by_label]


def format_minimal_context_segment(
    *,
    billed: int,
    tier: int,
    context_remaining: Optional[int] = None,
    context_budget: Optional[int] = None,
) -> str:
    """Build a compact ``C:`` segment showing cliff or window proximity only."""
    from monitor.lib.colors import blue, red, reset, yellow

    if isinstance(billed, int) and billed > 0 and isinstance(tier, int) and tier > 0:
        cliff_pct = 100.0 * billed / tier
        color = red if cliff_pct >= 100 else (yellow if cliff_pct >= 70 else blue)
        pct_str = f"{cliff_pct:.2f}%" if cliff_pct < 1.0 else f"{cliff_pct:.0f}%"
        return f"{color}{pct_str}{reset}"

    if (
        isinstance(context_remaining, int)
        and isinstance(context_budget, int)
        and context_budget > 0
    ):
        remaining_pct = max(0.0, 100.0 * context_remaining / context_budget)
        color = red if remaining_pct <= 10 else (yellow if remaining_pct <= 30 else blue)
        return f"{color}{remaining_pct:.0f}%{reset}"

    return ""


def format_coding_cost_suffix(session_cost: float) -> str:
    """Build the ``(~T:$…)`` cost annotation for coding mode (no W/P slots)."""
    from monitor.lib.display_output import _format_dollars

    if session_cost <= 0:
        return ""
    cost_str = _format_dollars(session_cost, cumulative=True)
    return f" (~T:${cost_str})"


def compaction_recovery_notice(*, manual: bool = False) -> str:
    """One-line user notice after automatic or manual compaction."""
    prefix = "Conversation compacted." if manual else "[notice] Context condensed to keep this thread reliable."
    return f"{prefix} {_RECOVERY_HINT}"


def chain_break_recovery_notice(*, had_chain: bool) -> str:
    """Optional recovery hint appended after a manual chain break."""
    if not had_chain:
        return ""
    return f" {_RECOVERY_HINT}"


def print_cliff_streak_warning_if_needed() -> None:
    """Print a one-line cliff warning when turns remain above the 2x tier."""
    global _LAST_CLIFF_WARNING_AT

    turns_over = int(getattr(config, "SESSION_TURNS_OVER_CLIFF", 0) or 0)
    if turns_over < CLIFF_STREAK_WARN_THRESHOLD:
        return
    if turns_over == _LAST_CLIFF_WARNING_AT:
        return

    _LAST_CLIFF_WARNING_AT = turns_over
    tier = int(getattr(config, "RESPONSES_CHAIN_TIER_TOKENS", 128000) or 128000)
    print(
        f"[notice] {turns_over} consecutive turns above the {tier}-token 2x cost cliff. "
        f"{_RECOVERY_HINT}"
    )


def reset_cliff_warning_state() -> None:
    """Clear cliff-warning dedupe state (tests / session reset)."""
    global _LAST_CLIFF_WARNING_AT
    _LAST_CLIFF_WARNING_AT = 0


def status_line_command(arg: Optional[str] = None) -> None:
    """Show or set the status-line display mode.

    Usage:
        :status                 Show current mode and field sets.
        :status coding           Switch mode (minimal | coding | debug).
    """
    from monitor.lib.colors import print_yellow

    arg_text = "" if arg is None else str(arg).strip().lower()

    if arg_text in {"help", "?", "-h", "--help"}:
        print("Status-line display mode for the REPL prompt and TUI info bar.")
        print("Usage: : (or /) status [minimal|coding|debug|show]")
        print("  minimal — H: message count, C: cliff proximity")
        print("  coding  — H: C: U: (session cost) F:  (default)")
        print("  debug   — all gauges (R:, L:, RT:, cache mix)")
        return

    if arg_text in {"", "show", "current"}:
        mode = get_status_line_mode()
        print_yellow(f"Status-line mode: {mode}")
        print(f"Fields: {', '.join(sorted(_allowed_labels(mode)))}")
        return

    if arg_text not in VALID_STATUS_LINE_MODES:
        print_yellow(
            f"Unknown mode {arg_text!r}. Use: minimal | coding | debug | show."
        )
        return

    resolved = set_status_line_mode(arg_text)
    print_yellow(f"Status-line mode set to: {resolved}.")
