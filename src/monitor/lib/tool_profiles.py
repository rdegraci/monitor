"""Static tool-profile and temporary auto-widening helpers."""

from __future__ import annotations

import logging
import re
from typing import Iterable

from monitor import config

logger = logging.getLogger(__name__)

CORE_READ_GROUP = "core_read"
TASK_GROUP = "task"
EDIT_GROUP = "edit"
VERIFY_GROUP = "verify"
NETWORK_GROUP = "network"
DB_GROUP = "db"
MEMORY_GROUP = "memory"
AGENT_GROUP = "agent"

TOOL_GROUPS = {
    CORE_READ_GROUP: {
        "perform_git_status",
        "perform_git_diff",
        "perform_git_diff_file",
        "perform_git_diff_previous",
        "perform_git_show",
        "search_commit_history",
        "blame_lines",
        "perform_git_diff_range",
        "list_directory_contents",
        "cat_file",
        "cat_file_range",
        "file_type",
        "find_files",
        "ripgrep_search_tool",
    },
    TASK_GROUP: {
        "add_todo",
        "add_discovered_work",
        "list_todos",
        "update_todo",
        "delete_todo",
        "clear_todos",
        "get_task_context",
        "set_task_acceptance",
        "save_task_checkpoint",
        "record_task_scope_change",
    },
    EDIT_GROUP: {
        "modify_source_code",
        "create_file",
        "make_directory",
        "bulk_replace_in_files",
        "text_file_or_directory_view",
        "text_file_create",
        "text_file_str_replace_in_file",
        "text_file_insert_text_at_line",
        "str_replace_based_edit_tool",
        "str_replace_editor",
    },
    VERIFY_GROUP: {
        "run_python_tests",
        "type_check_python",
    },
    NETWORK_GROUP: {
        "tavily_search",
        "get_current_weather",
    },
    DB_GROUP: {
        "execute_duckdb",
        "execute_psql",
        "execute_mc",
        "train_model",
        "evaluate_model",
        "deploy_model",
        "monitor_model_performance",
    },
    MEMORY_GROUP: {
        "save_to_memory",
        "read_from_memory",
        "update_memory",
        "fetch_memory_keys_as_json",
        "delete_from_memory",
    },
    AGENT_GROUP: {
        "agent_create",
        "agent_kill",
        "agent_list",
        "agent_logfile",
        "agent_send",
        "agent_gather",
    },
}

TOOL_NAME_TO_GROUP = {
    tool_name: group_name
    for group_name, tool_names in TOOL_GROUPS.items()
    for tool_name in tool_names
}

PROFILE_GROUPS = {
    "minimal": (CORE_READ_GROUP, TASK_GROUP),
    "coding": (CORE_READ_GROUP, TASK_GROUP, EDIT_GROUP, VERIFY_GROUP),
    "review": (CORE_READ_GROUP, TASK_GROUP, VERIFY_GROUP),
    "full": tuple(TOOL_GROUPS.keys()),
}

_PROFILE_INTENT_PATTERNS = {
    VERIFY_GROUP: (
        re.compile(r"\bcode review\b", re.IGNORECASE),
        re.compile(r"\breview\b", re.IGNORECASE),
        re.compile(r"\baudit\b", re.IGNORECASE),
        re.compile(r"\breview for\b", re.IGNORECASE),
        re.compile(r"\bcheck for regressions\b", re.IGNORECASE),
        re.compile(r"\blook for bugs\b", re.IGNORECASE),
        re.compile(r"\brun tests?\b", re.IGNORECASE),
        re.compile(r"\bfailing tests?\b", re.IGNORECASE),
        re.compile(r"\bunit tests?\b", re.IGNORECASE),
        re.compile(r"\btype-?check\b", re.IGNORECASE),
        re.compile(r"\bverify\b", re.IGNORECASE),
    ),
    EDIT_GROUP: (
        re.compile(r"\bfix\b", re.IGNORECASE),
        re.compile(r"\bbug\b", re.IGNORECASE),
        re.compile(r"\bimplement\b", re.IGNORECASE),
        re.compile(r"\badd (?:a )?feature\b", re.IGNORECASE),
        re.compile(r"\badd support for\b", re.IGNORECASE),
        re.compile(r"\bbuild\b", re.IGNORECASE),
        re.compile(r"\bwrite code\b", re.IGNORECASE),
        re.compile(r"\bedit\b", re.IGNORECASE),
        re.compile(r"\bmodify\b", re.IGNORECASE),
        re.compile(r"\bpatch\b", re.IGNORECASE),
        re.compile(r"\brefactor\b", re.IGNORECASE),
        re.compile(r"\brename\b", re.IGNORECASE),
        re.compile(r"\bchange\b.{0,24}\b(?:code|function|file|implementation)\b", re.IGNORECASE | re.DOTALL),
    ),
}

AUTO_WIDENABLE_GROUPS = {
    EDIT_GROUP,
    VERIFY_GROUP,
    NETWORK_GROUP,
    DB_GROUP,
    MEMORY_GROUP,
    AGENT_GROUP,
}

_EXPLICIT_GROUP_PATTERNS = {
    NETWORK_GROUP: (
        re.compile(r"\bsearch (?:the )?web\b", re.IGNORECASE),
        re.compile(r"\bweb search\b", re.IGNORECASE),
        re.compile(r"\bbrowse (?:the )?web\b", re.IGNORECASE),
        re.compile(r"\bsearch online\b", re.IGNORECASE),
        re.compile(r"\blook (?:it|this|that) up online\b", re.IGNORECASE),
        re.compile(r"\btavily\b", re.IGNORECASE),
        re.compile(r"\bweather\b", re.IGNORECASE),
    ),
    DB_GROUP: (
        re.compile(r"\b(?:query|inspect|check|run)\b.{0,40}\b(?:postgres|psql|duckdb|motherduck|database|db)\b", re.IGNORECASE | re.DOTALL),
        re.compile(r"\b(?:run|execute)\b.{0,24}\b(?:sql|psql|duckdb)\b", re.IGNORECASE | re.DOTALL),
    ),
    MEMORY_GROUP: (
        re.compile(r"\bremember this\b", re.IGNORECASE),
        re.compile(r"\bwhat do you remember\b", re.IGNORECASE),
        re.compile(r"\bforget this\b", re.IGNORECASE),
        re.compile(r"\bmemory tool\b", re.IGNORECASE),
    ),
    AGENT_GROUP: (
        re.compile(r"\bsub-?agent\b", re.IGNORECASE),
        re.compile(r"\bspawn an? agent\b", re.IGNORECASE),
        re.compile(r"\borchestrate\b", re.IGNORECASE),
        re.compile(r"\bagent_(?:create|send|gather|list|kill)\b", re.IGNORECASE),
    ),
}


def normalize_profile_name(profile: str | None) -> str:
    """Return a valid static profile name, falling back to the default."""
    if isinstance(profile, str):
        cleaned = profile.strip().lower()
        if cleaned in PROFILE_GROUPS:
            return cleaned
    return "coding"


def descriptor_name(descriptor) -> str | None:
    """Return the logical tool name from a descriptor entry."""
    if not isinstance(descriptor, dict):
        return None
    nested = descriptor.get("function")
    if isinstance(nested, dict):
        name = nested.get("name")
        if isinstance(name, str) and name:
            return name
    name = descriptor.get("name")
    if isinstance(name, str) and name:
        return name
    return None


def filter_descriptors_by_names(descriptors, allowed_names: Iterable[str] | None):
    """Return only descriptors whose tool names appear in ``allowed_names``."""
    if allowed_names is None:
        return list(descriptors) if isinstance(descriptors, list) else descriptors
    allowed = {name for name in allowed_names if isinstance(name, str) and name}
    if not isinstance(descriptors, list):
        return descriptors
    return [
        descriptor
        for descriptor in descriptors
        if descriptor_name(descriptor) in allowed
    ]


def profile_groups(profile: str | None) -> tuple[str, ...]:
    """Return the configured group tuple for a profile."""
    return PROFILE_GROUPS.get(normalize_profile_name(profile), PROFILE_GROUPS["coding"])


def allowed_tool_names_for_profile(
    profile: str | None = None,
    *,
    extra_groups: Iterable[str] | None = None,
) -> set[str]:
    """Resolve the allowed tool names for a base profile plus temporary groups."""
    groups = set(profile_groups(profile))
    for group in extra_groups or ():
        if group in TOOL_GROUPS:
            groups.add(group)
    allowed_names = set()
    for group in groups:
        allowed_names.update(TOOL_GROUPS.get(group, ()))
    return allowed_names


def current_extra_groups() -> set[str]:
    """Return the current turn's temporary tool groups."""
    groups = getattr(config, "CURRENT_TURN_TOOL_GROUPS", None)
    if isinstance(groups, set):
        return set(groups)
    if isinstance(groups, (list, tuple)):
        return {group for group in groups if isinstance(group, str)}
    return set()


def group_for_tool_name(tool_name: str | None) -> str | None:
    """Return the internal group name for a tool."""
    if not isinstance(tool_name, str) or not tool_name:
        return None
    return TOOL_NAME_TO_GROUP.get(tool_name)


def current_allowed_tool_names() -> set[str]:
    """Return allowed tool names for the active base profile + turn extras."""
    return allowed_tool_names_for_profile(
        getattr(config, "TOOL_PROFILE", "coding"),
        extra_groups=current_extra_groups(),
    )


def advertised_tool_descriptors_for_current_turn(descriptors):
    """Filter an advertised tool catalog for the active profile and turn extras."""
    if normalize_profile_name(getattr(config, "TOOL_PROFILE", "coding")) == "full":
        return list(descriptors) if isinstance(descriptors, list) else descriptors
    return filter_descriptors_by_names(descriptors, current_allowed_tool_names())


def _lease_turns_for_group(group: str) -> int:
    overrides = getattr(config, "TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP", None) or {}
    raw_value = overrides.get(group) if isinstance(overrides, dict) else None
    if raw_value is None:
        raw_value = getattr(config, "TOOL_PROFILE_AUTO_WIDEN_TURNS", 2)
    try:
        turns = int(raw_value)
    except (TypeError, ValueError):
        turns = 2
    return max(0, turns)


def activate_turn_tool_group_leases() -> tuple[set[str], set[str]]:
    """Activate leased temporary groups for this turn and decrement their timers."""
    leases = getattr(config, "TOOL_PROFILE_GROUP_LEASES", None)
    if not isinstance(leases, dict):
        leases = {}
    active = set()
    updated = {}
    expired = set()
    for group, raw_remaining in leases.items():
        if group not in AUTO_WIDENABLE_GROUPS:
            continue
        try:
            remaining = int(raw_remaining)
        except (TypeError, ValueError):
            continue
        if remaining <= 0:
            expired.add(group)
            continue
        active.add(group)
        post_turn_remaining = remaining - 1
        if post_turn_remaining > 0:
            updated[group] = post_turn_remaining
        else:
            expired.add(group)
    config.TOOL_PROFILE_GROUP_LEASES = updated
    config.CURRENT_TURN_TOOL_GROUPS = active
    return active, expired


def detect_explicit_auto_widen_groups(user_text: str | None) -> set[str]:
    """Return temporary groups explicitly requested by the user text."""
    if not user_text or not isinstance(user_text, str):
        return set()
    detected = set()
    for group, patterns in _PROFILE_INTENT_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(user_text):
                detected.add(group)
                break
    for group, patterns in _EXPLICIT_GROUP_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(user_text):
                detected.add(group)
                break
    return detected


def _disabled_auto_widen_groups() -> set[str]:
    raw = getattr(config, "TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS", None)
    if isinstance(raw, (list, tuple, set)):
        return {
            str(entry).strip().lower()
            for entry in raw
            if isinstance(entry, str) and entry.strip()
        }
    return set()


def _max_auto_widen_groups() -> int:
    raw = getattr(config, "TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS", 2)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 2
    return max(0, value)


def maybe_apply_explicit_auto_widen(
    user_text: str | None,
    *,
    notify=None,
) -> set[str]:
    """Add temporary groups for explicit user requests and refresh their leases."""
    if not getattr(config, "ENABLE_TOOL_PROFILE_AUTO_WIDEN", True):
        return set()
    if normalize_profile_name(getattr(config, "TOOL_PROFILE", "coding")) == "full":
        return set()

    detected = detect_explicit_auto_widen_groups(user_text)
    if not detected:
        return set()

    disabled = _disabled_auto_widen_groups()
    detected = {group for group in detected if group not in disabled}
    if not detected:
        return set()

    base_profile = normalize_profile_name(getattr(config, "TOOL_PROFILE", "coding"))
    base_groups = set(profile_groups(base_profile))
    detected = {group for group in detected if group not in base_groups}
    if not detected:
        return set()

    current_groups = current_extra_groups()
    leases = getattr(config, "TOOL_PROFILE_GROUP_LEASES", None)
    if not isinstance(leases, dict):
        leases = {}

    max_groups = _max_auto_widen_groups()
    active_before = set(current_groups) | {
        group for group, remaining in leases.items()
        if group in AUTO_WIDENABLE_GROUPS and isinstance(remaining, int) and remaining > 0
    }
    activated = set()
    refresh_on_use = bool(getattr(config, "TOOL_PROFILE_AUTO_WIDEN_REFRESH_ON_USE", True))

    for group in sorted(detected):
        if group not in AUTO_WIDENABLE_GROUPS:
            continue
        already_active = group in active_before or group in current_groups
        if not already_active and max_groups > 0 and len(active_before) >= max_groups:
            logger.info(
                "Skipping temporary tool-group auto-widen for %s: max active groups cap %s reached.",
                group,
                max_groups,
            )
            continue

        current_groups.add(group)
        activated.add(group)
        if refresh_on_use or not already_active:
            leases[group] = _lease_turns_for_group(group)
        active_before.add(group)

    config.CURRENT_TURN_TOOL_GROUPS = current_groups
    config.TOOL_PROFILE_GROUP_LEASES = leases

    if activated and callable(notify):
        lease_parts = []
        for group in sorted(activated):
            lease_parts.append(f"{group}:{_lease_turns_for_group(group)}")
        notify(
            "temporary widen → "
            + ", ".join(sorted(activated))
            + f" (future-turn lease {', '.join(lease_parts)})"
        )

    return activated


def refresh_tool_group_lease_for_tool(tool_name: str | None) -> bool:
    """Refresh a temporary group's lease when one of its tools is actually used."""
    if not bool(getattr(config, "TOOL_PROFILE_AUTO_WIDEN_REFRESH_ON_USE", True)):
        return False
    group = group_for_tool_name(tool_name)
    if group not in AUTO_WIDENABLE_GROUPS:
        return False
    current_groups = current_extra_groups()
    if group not in current_groups:
        return False
    leases = getattr(config, "TOOL_PROFILE_GROUP_LEASES", None)
    if not isinstance(leases, dict):
        leases = {}
    leases[group] = _lease_turns_for_group(group)
    config.TOOL_PROFILE_GROUP_LEASES = leases
    return True


def tool_profile_snapshot() -> dict:
    """Return a compact runtime snapshot for the current tool-profile state."""
    base_profile = normalize_profile_name(getattr(config, "TOOL_PROFILE", "coding"))
    current_groups_snapshot = sorted(current_extra_groups())
    leases = getattr(config, "TOOL_PROFILE_GROUP_LEASES", None)
    if not isinstance(leases, dict):
        leases = {}
    cleaned_leases = {}
    for group, remaining in leases.items():
        try:
            turns = int(remaining)
        except (TypeError, ValueError):
            continue
        if turns > 0:
            cleaned_leases[group] = turns
    base_groups = list(profile_groups(base_profile))
    allowed_names = allowed_tool_names_for_profile(
        base_profile, extra_groups=current_groups_snapshot
    )
    return {
        "base_profile": base_profile,
        "base_groups": base_groups,
        "current_turn_groups": current_groups_snapshot,
        "leased_groups": cleaned_leases,
        "allowed_tool_names": sorted(allowed_names),
    }


def profile_names() -> list[str]:
    """Return user-facing static profile names in stable order."""
    return list(PROFILE_GROUPS.keys())
