"""Unified command discovery (PLAN Phase 4).

Presents Monitor commands by user task instead of internal implementation
categories (built-ins vs catalogs vs macros). Canonical entry points are
``:help``, ``/help``, and ``?``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Task-oriented categories, shown in this order.
CATEGORY_ORDER: Tuple[str, ...] = (
    "coding",
    "repository",
    "session",
    "cost",
    "agent",
    "configuration",
    "advanced",
)

CATEGORY_TITLES: Dict[str, str] = {
    "coding": "Coding",
    "repository": "Repository",
    "session": "Session",
    "cost": "Cost",
    "agent": "Agent",
    "configuration": "Configuration",
    "advanced": "Advanced",
}

# Alias name → canonical command name. Aliases stay registered for invocation
# but help lists the canonical name and reports the relationship.
COMMAND_ALIASES: Dict[str, str] = {
    "?": "help",
    "built_ins": "help",
    "model": "llm",
    "cc": "copy_code",
}

# Explicit category placement. Unlisted registered commands fall into advanced.
COMMAND_CATEGORIES: Dict[str, str] = {
    # coding
    "tools": "coding",
    "activity": "coding",
    "reasoning": "coding",
    "status": "configuration",
    "tasks": "coding",
    "clear_tasks": "coding",
    "less": "coding",
    "save_response": "coding",
    "copy_code": "coding",
    "power_user": "coding",
    "design_mode": "coding",
    "dev_mode": "coding",
    # repository
    "rg": "repository",
    "make_commit": "repository",
    "next_steps": "repository",
    "wiki_init": "repository",
    "wiki_lint": "repository",
    "wiki_fix": "repository",
    "symbols": "repository",
    # session
    "reset_history": "session",
    "break_chain": "session",
    "compact": "session",
    "history": "session",
    "history_size": "session",
    "dump_history": "session",
    "load_history": "session",
    "sessions": "session",
    # cost
    "cost_debug": "cost",
    "fuel_debug": "cost",
    "dump_metrics": "cost",
    # agent
    "agent": "agent",
    # configuration
    "llm": "configuration",
    "ttl": "configuration",
    "max_tokens": "configuration",
    "settings": "configuration",
    "preferences": "configuration",
    "edit_function_keys": "configuration",
    # advanced (also the default for unlisted commands)
    "help": "advanced",
    "commands": "advanced",
    "macros": "advanced",
    "edit_macros": "advanced",
    "reload_macros": "advanced",
    "repl": "advanced",
    "memories": "advanced",
    "clean_csv": "advanced",
    "normalize_csv": "advanced",
    "add_db_tools": "advanced",
    "remove_db_tools": "advanced",
    "add_modelling_tools": "advanced",
    "remove_modelling_tools": "advanced",
    "embed": "advanced",
    "query": "advanced",
    "index": "advanced",
    "semstore": "advanced",
    "twitch": "advanced",
    "joke": "advanced",
    "tweet": "advanced",
    "twitch_summary": "advanced",
    "linkedin_summary": "advanced",
}

# Short examples shown on the overview and on matching command detail pages.
FEATURED_EXAMPLES: Tuple[Tuple[str, str], ...] = (
    (":tools", "Show or set the tool profile (:tools list, :tools coding, :tools full)"),
    (":compact", "Summarize older history to reclaim context"),
    (":break_chain", "Drop the Responses chain; keep history (cost-cliff recovery)"),
    (":reasoning medium", "Set reasoning effort (minimal|low|medium|high|xhigh)"),
    (":cost_debug", "Inspect per-turn cost tracking and invariant flags"),
    (":reset_history", "Clear conversation history for a fresh task"),
)

COMMAND_EXAMPLES: Dict[str, Tuple[str, ...]] = {
    "tools": (":tools", ":tools list", ":tools coding", ":tools full", ":tools tokens"),
    "compact": (":compact",),
    "break_chain": (":break_chain",),
    "reasoning": (":reasoning", ":reasoning medium", ":reasoning help"),
    "cost_debug": (":cost_debug",),
    "fuel_debug": (":fuel_debug",),
    "dump_metrics": (":dump_metrics", ":dump_metrics /tmp/metrics.json"),
    "reset_history": (":reset_history",),
    "llm": (":llm", ":llm help", ":llm gpt-4o-mini"),
    "activity": (":activity", ":activity off", ":activity on"),
    "status": (":status", ":status coding", ":status debug"),
    "agent": (":agent", ":agent list", ":agent help"),
    "copy_code": (":copy_code", ":copy_code 2", ":copy_code all"),
    "rg": (":rg pattern", ":rg -t py ClassName"),
    "symbols": (":symbols", ":symbols cache", ":symbols langs"),
}


def normalize_help_invocation(command: Optional[str]) -> Optional[str]:
    """Rewrite bare ``?`` / ``:?`` / ``/?`` into a ``:help`` invocation.

    Args:
        command: Raw user input.

    Returns:
        A ``:help``-prefixed command string when the input is a help shortcut,
        otherwise ``None`` (caller should keep the original).
    """
    if not isinstance(command, str):
        return None
    stripped = command.strip()
    if not stripped:
        return None

    if stripped == "?":
        return ":help"
    if stripped.startswith("? "):
        return f":help {stripped[1:].lstrip()}"

    if stripped in (":?", "/?"):
        return ":help"
    if stripped.startswith(":? "):
        return f":help {stripped[3:].lstrip()}"
    if stripped.startswith("/? "):
        return f":help {stripped[3:].lstrip()}"
    return None


def canonical_command_name(name: str) -> str:
    """Return the canonical name for a command or alias."""
    key = (name or "").strip().lstrip(":/")
    return COMMAND_ALIASES.get(key, key)


def category_for_command(name: str) -> str:
    """Return the task category for a command name (aliases resolve first)."""
    canonical = canonical_command_name(name)
    return COMMAND_CATEGORIES.get(canonical, "advanced")


def aliases_for_command(name: str) -> List[str]:
    """Return registered alias names that point at ``name``."""
    canonical = canonical_command_name(name)
    return sorted(alias for alias, target in COMMAND_ALIASES.items() if target == canonical)


def _dedupe_built_ins(entries: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the first registration for each command name."""
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for item in entries:
        name = item.get("command")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        result.append(item)
    return result


def registered_built_ins() -> List[Dict[str, Any]]:
    """Return deduplicated built-in command descriptors from the live registry."""
    from monitor.lib.built_ins_utils import built_in_functions

    return _dedupe_built_ins(built_in_functions)


def public_command_names() -> List[str]:
    """Return sorted canonical public command names (aliases excluded)."""
    names: List[str] = []
    for item in registered_built_ins():
        name = item.get("command")
        if not isinstance(name, str):
            continue
        if name in COMMAND_ALIASES:
            continue
        names.append(name)
    return sorted(set(names))


def _description_for(name: str, registry: Dict[str, Dict[str, Any]]) -> str:
    entry = registry.get(name) or registry.get(canonical_command_name(name))
    if not entry:
        return ""
    return str(entry.get("description") or "").strip()


def _registry_index(entries: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item["command"]): item
        for item in entries
        if isinstance(item.get("command"), str)
    }


def _format_command_line(name: str, description: str, width: int) -> str:
    display = f":{name}"
    aliases = aliases_for_command(name)
    if aliases:
        alias_text = ", ".join(f":{a}" for a in aliases if a != "?")
        if alias_text:
            display = f"{display} (alias: {alias_text})"
    padded = display.ljust(width)
    if description:
        return f"{padded}  {description}"
    return padded.rstrip()


def _max_display_width(names: Sequence[str]) -> int:
    width = 0
    for name in names:
        display = f":{name}"
        aliases = aliases_for_command(name)
        alias_text = ", ".join(f":{a}" for a in aliases if a != "?")
        if alias_text:
            display = f"{display} (alias: {alias_text})"
        width = max(width, len(display))
    return max(width, 12)


def _commands_in_category(
    category: str, registry: Dict[str, Dict[str, Any]]
) -> List[str]:
    names = [
        name
        for name in registry
        if name not in COMMAND_ALIASES and category_for_command(name) == category
    ]
    # Common-first: featured example commands, then alphabetical.
    featured_order = [
        example.split()[0].lstrip(":/") for example, _ in FEATURED_EXAMPLES
    ]

    def sort_key(name: str) -> Tuple[int, str]:
        try:
            return (featured_order.index(name), name)
        except ValueError:
            return (len(featured_order), name)

    return sorted(names, key=sort_key)


def _render_overview(registry: Dict[str, Dict[str, Any]]) -> List[str]:
    lines: List[str] = [
        "Monitor help — type a command with ':' or '/' (both work).",
        "Search: :help <command|category>   Categories: "
        + ", ".join(CATEGORY_ORDER),
        "",
        "Common actions:",
    ]
    for example, blurb in FEATURED_EXAMPLES:
        lines.append(f"  {example:<22}  {blurb}")

    for category in CATEGORY_ORDER:
        names = _commands_in_category(category, registry)
        if not names:
            continue
        lines.append("")
        lines.append(f"=== {CATEGORY_TITLES.get(category, category.title())} ===")
        width = _max_display_width(names)
        for name in names:
            lines.append(
                _format_command_line(name, _description_for(name, registry), width)
            )

    lines.extend(
        [
            "",
            "Advanced notes:",
            "  :macros / :edit_macros     User macro expansions (not built-ins).",
            "  :commands                  Terminal/internal catalog names (llm<, directive<, …).",
            "  Tcl / social / CSV / RAG   Listed under Advanced above.",
            "",
            "Tip: :help tools   :help session   :help cost",
        ]
    )
    return lines


def _render_category(
    category: str, registry: Dict[str, Dict[str, Any]]
) -> List[str]:
    names = _commands_in_category(category, registry)
    title = CATEGORY_TITLES.get(category, category.title())
    if not names:
        return [f"No commands registered in category '{category}'."]
    lines = [f"=== {title} ===", ""]
    width = _max_display_width(names)
    for name in names:
        lines.append(
            _format_command_line(name, _description_for(name, registry), width)
        )
    return lines


def _render_command_detail(
    name: str, registry: Dict[str, Dict[str, Any]]
) -> List[str]:
    canonical = canonical_command_name(name)
    description = _description_for(canonical, registry) or _description_for(
        name, registry
    )
    lines: List[str] = []
    if name != canonical and name in COMMAND_ALIASES:
        lines.append(f":{name} is an alias for :{canonical}")
        lines.append("")
    lines.append(f":{canonical}")
    if description:
        lines.append(f"  {description}")
    lines.append(f"  Category: {category_for_command(canonical)}")
    alias_names = aliases_for_command(canonical)
    visible_aliases = [a for a in alias_names if a != "?"]
    if visible_aliases:
        lines.append(
            "  Aliases: " + ", ".join(f":{a}" for a in visible_aliases)
        )
    examples = COMMAND_EXAMPLES.get(canonical, ())
    if examples:
        lines.append("  Examples:")
        for example in examples:
            lines.append(f"    {example}")
    return lines


def _search(
    query: str, registry: Dict[str, Dict[str, Any]]
) -> List[Tuple[str, str]]:
    needle = query.lower().strip()
    hits: List[Tuple[str, str]] = []
    for name, entry in registry.items():
        if name in COMMAND_ALIASES:
            # Still allow searching by alias name.
            canonical = COMMAND_ALIASES[name]
            desc = _description_for(canonical, registry)
            hay = f"{name} {canonical} {desc}".lower()
            if needle in hay:
                hits.append((name, desc))
            continue
        desc = str(entry.get("description") or "")
        hay = f"{name} {desc}".lower()
        if needle in hay:
            hits.append((name, desc))
    hits.sort(key=lambda item: (item[0] in COMMAND_ALIASES, item[0]))
    return hits


def format_help(arg: Optional[str] = None) -> str:
    """Return the help text for an optional query string."""
    registry = _registry_index(registered_built_ins())
    query = (arg or "").strip()

    if not query:
        return "\n".join(_render_overview(registry))

    lowered = query.lower()
    if lowered in CATEGORY_ORDER or lowered in {
        title.lower() for title in CATEGORY_TITLES.values()
    }:
        category = lowered
        for key, title in CATEGORY_TITLES.items():
            if title.lower() == lowered:
                category = key
                break
        return "\n".join(_render_category(category, registry))

    lookup = query.lstrip(":/")
    if lookup in registry or lookup in COMMAND_ALIASES:
        return "\n".join(_render_command_detail(lookup, registry))

    hits = _search(lookup, registry)
    if not hits:
        return (
            f"No commands matching '{query}'.\n"
            f"Try :help, or a category: {', '.join(CATEGORY_ORDER)}"
        )

    lines = [f"Matches for '{query}':", ""]
    width = _max_display_width([canonical_command_name(name) for name, _ in hits])
    seen_canonical: set[str] = set()
    for name, desc in hits:
        canonical = canonical_command_name(name)
        if canonical in seen_canonical and name in COMMAND_ALIASES:
            lines.append(f":{name} → :{canonical}")
            continue
        seen_canonical.add(canonical)
        if name in COMMAND_ALIASES:
            lines.append(f":{name} → :{canonical}")
            lines.append(
                _format_command_line(canonical, desc or _description_for(canonical, registry), width)
            )
        else:
            lines.append(_format_command_line(name, desc, width))
    return "\n".join(lines)


def help_command(arg: Optional[str] = None) -> None:
    """Print unified command help. Invoked as ``:help``, ``/help``, or ``?``."""
    print(format_help(arg))
    print("***")


def is_command_discoverable(name: str) -> bool:
    """Return True when a public command appears in overview or by name search."""
    canonical = canonical_command_name(name)
    registry = _registry_index(registered_built_ins())
    if canonical not in registry and name not in registry:
        return False
    overview = format_help("")
    detail = format_help(canonical)
    return f":{canonical}" in overview or f":{canonical}" in detail
