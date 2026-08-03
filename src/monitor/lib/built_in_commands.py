import difflib
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict

from monitor._stubs import appdirs
from monitor.lib import freemicro, llm_utils
from colored import attr, fg
from monitor.lib.pygments_stubs import BashLexer, MarkdownLexer, TerminalFormatter, highlight

from monitor import config
from monitor.function_keys_loader import load_function_keys_config
from monitor.lib.built_ins_compaction_utils import (
    compact_command,
    compact_history_command,
)
from monitor.lib.built_ins_data_utils import (
    clean_missing_values_command,
    normalize_data_command,
)
from monitor.lib.built_ins_editor_utils import (
    edit_function_keys_command,
    edit_macros_command,
    open_function_keys_editor,
    open_preferences_command,
    reload_macros_command,
)
from monitor.lib.built_ins_external_utils import (
    deploy_model_command,
    linkedin_summary_command,
    monitor_model_performance_command,
    twitch_summary_command,
)
from monitor.lib.session_artifacts import get_sessions_root, list_most_recent_session_folders
from monitor.lib.built_ins_history_utils import (
    _format_elapsed,
    cost_debug_command,
    break_chain_command,
    dump_history_command,
    dump_metrics_command,
    fuel_debug_command,
    load_history_command,
    reset_conversation_history_command,
)
from monitor.lib.built_ins_response_utils import (
    _extract_fenced_code_blocks,
    _last_assistant_response,
    copy_code_command,
    less_command,
    save_response_command,
)
from monitor.lib.built_ins_runtime_utils import (
    llm_command,
    max_tokens_command,
    reasoning_command,
    settings_command,
    ttl_command,
)
from monitor.lib.built_ins_shell_utils import (
    clear_screen,
    handle_cd_command,
    print_debug,
)
from monitor.lib.built_ins_wiki_utils import (
    WIKI_FIX_MAX_DIFF_LINES,
    WIKI_FIX_MAX_REPLACEMENT_CHARACTERS,
    WIKI_FIX_MAX_REPLACEMENT_LINES,
    WIKI_INIT_MAX_DRAFT_CHARACTERS,
    WIKI_INIT_MAX_DRAFT_LINES,
    build_repo_orientation_context,
    latest_wiki_fix_preview,
    latest_wiki_init_draft,
    store_latest_wiki_fix_preview,
    store_latest_wiki_init_draft,
    wiki_fix_diff_line_count,
)
from monitor.lib.colors import print_yellow
from monitor.lib.display_output import print_colored_error
from monitor.lib.external_services import (
    joke_for_twitch,
    send_artifact,
    send_file_to_indexing_service,
    send_linkedin_message,
    send_twitter_message,
    send_twitch_message_command,
)
# Note: ``adjust_history_size`` is imported lazily inside the call site below
# to avoid a module-load cycle when something imports ``monitor.lib.history``
# directly (e.g., tests). See the analogous note in monitor/lib/redis_utils.py.
from monitor.lib.keyboard import configure_function_key_insertions
from monitor.lib.monitor_wiki import (
    configured_project_wiki_index_path,
    ensure_configured_project_wiki,
    has_substantive_configured_project_wiki,
)
from monitor.lib.monitor_wiki_linter import latest_wiki_lint_result, run_project_wiki_lint_mode
from monitor.lib.preferences import open_preferences_editor
from monitor.lib.summarizers import summarize_conversation_for_linkedin
from monitor.lib.summarizers import summarize_conversation_for_twitch
from monitor.lib.system_prompt import build_system_prompt, clear_project_instructions_cache
from monitor.lib.tool_loading import list_tools
from monitor.lib.tool_profiles import (
    DEFAULT_TOOL_PROFILE,
    PROFILE_SUMMARIES,
    NON_CODING_GROUPS,
    profile_names,
    profile_phrase_snapshot,
    profile_schema_token_report,
    tool_profile_snapshot,
)

reasoning_command.__globals__["config"] = config
llm_command.__globals__["config"] = config
ttl_command.__globals__["config"] = config
max_tokens_command.__globals__["config"] = config

logger = logging.getLogger(__name__)

_SUPPORTED_WIKI_FIX_KINDS = {
    "semantic_stale_location_claim",
    "semantic_stale_authority_claim",
    "semantic_stale_workflow_claim",
    "semantic_stale_ownership_claim",
}


def sessions_command(arg=None):
    """Print the five most recent session folder paths.

    Args:
        arg: Optional dispatcher argument.

    Returns:
        None.
    """
    if arg is not None and str(arg).strip() in {"help", "?", "-h", "--help"}:
        print("Print the five most recent session folder paths.")
        print("Usage: : (or /) sessions")
        return

    root = get_sessions_root()
    folders = list_most_recent_session_folders(limit=5)
    if not folders:
        print(f"No session folders found under {root}")
        return
    for folder in folders:
        print(str(folder.resolve()))


def print_tools_command(arg=None):
    from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE
    from monitor.lib.llm_utils import get_tools_for_model

    arg_text = "" if arg is None else str(arg).strip().lower()
    valid_profiles = profile_names()

    if arg_text in {"help", "?", "-h", "--help"}:
        print("Show or set the static tool profile used to advertise tools to the model.")
        print(
            f"Default profile is '{DEFAULT_TOOL_PROFILE}' — read/search/git, task, edit, "
            "verify, and memory tools for normal repository work."
        )
        print("Usage: : (or /) tools [show|list|catalog|tokens|minimal|coding|review|full]")
        print("Examples:")
        print("  :tools")
        print("  :tools list")
        print("  :tools coding")
        print("  :tools catalog")
        print("  :tools tokens")
        return

    if arg_text == "list":
        print("Available tool profiles:")
        for name in profile_names():
            summary = PROFILE_SUMMARIES.get(name, "")
            suffix = " (default)" if name == DEFAULT_TOOL_PROFILE else ""
            print(f"  {name}{suffix}  {summary}")
        print("")
        print("Groups excluded from the default coding profile until widened:")
        print(f"  {', '.join(NON_CODING_GROUPS)}")
        print("Use ':tools phrases' to inspect auto-widen triggers.")
        return

    if arg_text == "phrases":
        phrases = profile_phrase_snapshot()
        print("Tool-profile widening phrases:")
        for group_name in ("network", "db", "memory", "agent", "edit", "verify"):
            print(f"  {group_name}:")
            for phrase in phrases.get(group_name, []):
                print(f"    - {phrase}")
        return

    if arg_text in valid_profiles:
        config.TOOL_PROFILE = arg_text
        config.CURRENT_TURN_TOOL_GROUPS = set()
        config.TOOL_PROFILE_GROUP_LEASES = {}
        print_yellow(f"Tool profile set to: {config.TOOL_PROFILE}")
        return

    snapshot = tool_profile_snapshot()
    tools, _tool_choice = get_tools_for_model(
        TOOL_DESCRIPTIONS,
        GEMINI_TOOL_DESCRIPTIONS,
        model_name=getattr(config, "MODEL", None),
        normalize_tools=False,
    )
    tools = tools or []
    tool_names = []
    for descriptor in tools:
        name = None
        if isinstance(descriptor, dict):
            if isinstance(descriptor.get("function"), dict):
                name = descriptor["function"].get("name")
            if not name:
                name = descriptor.get("name")
        if isinstance(name, str) and name:
            tool_names.append(name)

    if arg_text == "tokens":
        report = profile_schema_token_report(tools)
        print("Advertised tool-schema size by profile:")
        for profile_name in profile_names():
            entry = report.get(profile_name, {})
            print(
                f"  {profile_name}: tools={entry.get('tool_count', 0)} "
                f"schema_tokens={entry.get('schema_tokens', 0)}"
            )
        return

    if arg_text in {"catalog", "show_all", "names"}:
        print(f"Tool profile: {snapshot['base_profile']}")
        print(f"Current turn groups: {', '.join(snapshot['current_turn_groups']) or '(none)'}")
        print(f"Leased groups: {snapshot['leased_groups'] or '(none)'}")
        print(f"Advertised tools ({len(tool_names)}):")
        for name in tool_names:
            print(f"  {name}")
        return

    tools_info = list_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
    active_count = len(tool_names)
    loaded_count = len(tools_info) if isinstance(tools_info, dict) else 0
    print(f"Tool profile: {snapshot['base_profile']}")
    if snapshot["base_profile"] == DEFAULT_TOOL_PROFILE:
        print(f"Profile mode: {PROFILE_SUMMARIES.get(DEFAULT_TOOL_PROFILE, '')}")
        excluded = [group for group in NON_CODING_GROUPS if group not in snapshot["base_groups"]]
        if excluded:
            print(f"Excluded until widened: {', '.join(excluded)}")
    print(f"Base groups: {', '.join(snapshot['base_groups'])}")
    print(
        f"Current turn groups: "
        f"{', '.join(snapshot['current_turn_groups']) or '(none)'}"
    )
    print(f"Leased groups: {snapshot['leased_groups'] or '(none)'}")
    print(f"Advertised tool count: {active_count}")
    print(f"Loaded tool count: {loaded_count}")
    print("Use ':tools list' for profiles, ':tools catalog' for names, ':tools tokens' for schema size.")


def symbols_command(arg=None):
    """Show on-demand symbol support and payload-free cache diagnostics."""
    from monitor.lib.code_symbols import (
        EXTENSION_TO_LANGUAGE,
        symbol_cache_stats,
        symbol_dependency_status,
    )
    from monitor.lib.optional_deps import install_command

    arg_text = (arg or "").strip().lower()
    if arg_text not in {"", "cache", "langs", "languages", "help"}:
        print_colored_error("Usage: :symbols [cache|langs|help]")
        return
    if arg_text == "help":
        print("Usage: :symbols [cache|langs]")
        print("  cache  show in-process and session symbol counters")
        print("  langs  show supported extensions and grammar availability")
        return

    dependency_status = symbol_dependency_status()
    installed = all(dependency_status.values())
    if arg_text in {"", "langs", "languages"}:
        print(f"Symbol tools: {'ready' if installed else 'missing optional dependencies'}")
        by_language: Dict[str, list[str]] = {}
        for extension, language in sorted(EXTENSION_TO_LANGUAGE.items()):
            by_language.setdefault(language, []).append(extension)
        for language, extensions in sorted(by_language.items()):
            print(f"  {language}: {', '.join(extensions)}")
        if not installed:
            missing = [name for name, present in dependency_status.items() if not present]
            print(f"Missing modules: {', '.join(missing)}")
            print(f"Install: {install_command('symbols')}")

    if arg_text in {"", "cache"}:
        stats = symbol_cache_stats()
        print(
            "Symbol cache (process): "
            f"hits={stats.get('hits', 0)} misses={stats.get('misses', 0)}"
        )
        print(
            "Session symbols: "
            f"calls={int(getattr(config, 'SESSION_SYMBOL_TOOL_CALLS', 0) or 0)} "
            f"cache_hits={int(getattr(config, 'SESSION_SYMBOL_CACHE_HITS', 0) or 0)} "
            f"files={int(getattr(config, 'SESSION_SYMBOL_FILES_SCANNED', 0) or 0)} "
            f"results={int(getattr(config, 'SESSION_SYMBOL_RESULTS', 0) or 0)} "
            f"failures={int(getattr(config, 'SESSION_SYMBOL_FAILURES', 0) or 0)}"
        )


def activity_command(arg=None):
    """Show or toggle live turn/tool activity feedback (PLAN Phase 3).

    Usage:
        :activity            Show current state.
        :activity on|off     Enable or disable live feedback.
        :activity toggle     Flip the current state.
    """
    from monitor.lib import activity

    arg_text = "" if arg is None else str(arg).strip().lower()

    if arg_text in {"help", "?", "-h", "--help"}:
        print("Live turn/tool activity feedback (single in-place status line).")
        print("Usage: : (or /) activity [on|off|toggle|show]")
        print("Shows tool names and aggregate counters only — never arguments,")
        print("tool output, prompts, or credentials. Adds no model calls.")
        return

    current = bool(getattr(config, "LIVE_TURN_FEEDBACK", True))

    if arg_text in {"", "show", "status"}:
        rendering = activity.activity_enabled()
        print_yellow(
            f"Live activity feedback: {'on' if current else 'off'} "
            f"(currently rendering: {'yes' if rendering else 'no'})."
        )
        if current and not rendering:
            print("Not rendering because output is non-TTY, server, or sub-agent mode.")
        return

    if arg_text in {"on", "true", "enable", "enabled"}:
        config.LIVE_TURN_FEEDBACK = True
    elif arg_text in {"off", "false", "disable", "disabled", "quiet"}:
        config.LIVE_TURN_FEEDBACK = False
        activity.clear()
    elif arg_text == "toggle":
        config.LIVE_TURN_FEEDBACK = not current
        if not config.LIVE_TURN_FEEDBACK:
            activity.clear()
    else:
        print_yellow(f"Unknown option {arg_text!r}. Use: on | off | toggle | show.")
        return

    print_yellow(
        f"Live activity feedback set to: {'on' if config.LIVE_TURN_FEEDBACK else 'off'}."
    )



def freemicro_command(arg=None):
    """Show or toggle FreeMicro hook integration for the current session.

    Usage:
        :freemicro            Show current state.
        :freemicro on|off     Enable or disable FreeMicro hooks.
        :freemicro toggle     Flip the current state.
    """
    arg_text = "" if arg is None else str(arg).strip().lower()

    if arg_text in {"help", "?", "-h", "--help"}:
        print("FreeMicro hook integration for Codex Micro Agent Keys.")
        print("Usage: : (or /) freemicro [on|off|toggle|show]")
        print("Enabling emits Claude-shaped lifecycle events to 'freemicro hook'.")
        print("Requires 'freemicro' on PATH and a running FreeMicro daemon.")
        print("Runtime changes affect only this Monitor process.")
        return

    current = bool(getattr(config, "FREEMICRO_HOOKS", False))
    binary = freemicro._binary()
    binary_available = bool(binary)

    if arg_text in {"", "show", "status"}:
        print_yellow(
            f"FreeMicro hooks: {'on' if current else 'off'} "
            f"(binary available: {'yes' if binary_available else 'no'})."
        )
        if current and not binary_available:
            print("Hooks are enabled, but 'freemicro' is not on PATH.")
        return

    if arg_text in {"on", "true", "enable", "enabled"}:
        config.FREEMICRO_HOOKS = True
        freemicro.session_start()
    elif arg_text in {"off", "false", "disable", "disabled", "quiet"}:
        if current:
            freemicro.session_end(reason="disabled")
        config.FREEMICRO_HOOKS = False
    elif arg_text == "toggle":
        if current:
            freemicro.session_end(reason="disabled")
            config.FREEMICRO_HOOKS = False
        else:
            config.FREEMICRO_HOOKS = True
            freemicro.session_start()
    else:
        print_yellow(f"Unknown option {arg_text!r}. Use: on | off | toggle | show.")
        return

    print_yellow(
        f"FreeMicro hooks set to: {'on' if config.FREEMICRO_HOOKS else 'off'}."
    )

def _strip_markdown_fences(text):
    """Strip a single wrapping markdown code fence from LLM output.

    Args:
        text: Raw text that may be wrapped in a leading ```` ``` ```` fence.

    Returns:
        The text with one surrounding fenced block removed, if present.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _apply_wiki_init_draft(index_path, arg_parts):
    """Write the last drafted INDEX.md for the configured project wiki.

    Args:
        index_path: Resolved configured project wiki ``INDEX.md`` path.
        arg_parts: Lowercased argument tokens following ``apply``.

    Returns:
        dict | None: An apply result dict on success, otherwise ``None`` after
        printing a user-facing message.
    """
    if len(arg_parts) > 1 and arg_parts[1] != "force":
        print_colored_error("wiki_init apply takes no argument other than 'force'.")
        return None
    force = len(arg_parts) > 1 and arg_parts[1] == "force"

    draft = latest_wiki_init_draft()
    if not draft or not draft.get("content"):
        print_colored_error("No drafted INDEX.md is available. Run ':wiki_init' first.")
        return None
    if str(draft.get("index_path", "")) != str(index_path):
        print_colored_error(
            "The stored draft targets a different project wiki. Run ':wiki_init' again."
        )
        return None
    if has_substantive_configured_project_wiki() and not force:
        print_colored_error(
            "INDEX.md already has substantive content. "
            "Re-run with ':wiki_init apply force' to overwrite it."
        )
        return None

    try:
        Path(index_path).write_text(draft["content"], encoding="utf-8")
    except OSError as e:
        logger.error("Failed to write project wiki INDEX.md: %s", e, exc_info=True)
        print_colored_error(f"Failed to write project wiki INDEX.md: {e}")
        return None

    print(f"Wrote drafted INDEX.md to {index_path}")
    return {
        "mode": "apply",
        "index_path": str(index_path),
        "written": True,
        "forced": force,
    }


def wiki_init_command(arg=None):
    """Draft, and optionally write, a project-aware wiki ``INDEX.md``.

    Performs a quick, deterministic repository orientation pass (top-level
    layout, manifest files, README head), asks the LLM to draft a compact
    ``INDEX.md`` from that context, and either previews it or writes it to the
    configured project wiki.

    Args:
        arg: Dispatcher argument. ``None``/empty or ``preview`` drafts and
            prints without writing; ``apply`` writes the last draft (refusing to
            clobber substantive content); ``apply force`` overwrites substantive
            content; a help token prints usage.

    Returns:
        dict | None: A draft preview dict, an apply result dict, or ``None``
        when showing help, when no project wiki is configured, when arguments
        are invalid, or when a guardrail prevents the operation.
    """
    usage = (
        "Draft an INDEX.md for the configured project wiki from a quick repository orientation pass.\n"
        "Usage: : (or /) wiki_init              Draft and print the proposed INDEX.md (no write).\n"
        "       : (or /) wiki_init apply         Write the last draft (refuses if the wiki already has real content).\n"
        "       : (or /) wiki_init apply force   Overwrite an existing substantive INDEX.md with the last draft.\n"
        "Drafting is LLM-assisted and grounded in the repository manifest, README, and top-level layout. "
        "Review and edit the result; wiki content is yours to own."
    )
    raw_arg = "" if arg is None else str(arg).strip()
    lowered = raw_arg.lower()
    if lowered in {"help", "?", "-h", "--help"}:
        print(usage)
        return None

    try:
        project_dir = ensure_configured_project_wiki()
        if not project_dir:
            print(
                "No configured project wiki is available. Start Monitor inside a project, "
                "then run :wiki_init again."
            )
            return None

        index_path = configured_project_wiki_index_path()
        if index_path is None:
            print_colored_error("Could not resolve the project wiki INDEX.md path.")
            return None

        if lowered.startswith("apply"):
            return _apply_wiki_init_draft(index_path, lowered.split())

        if raw_arg and lowered != "preview":
            print_colored_error(
                "wiki_init accepts no argument (draft), 'apply', or 'apply force'."
            )
            return None

        identity_path = getattr(config, "PROJECT_WIKI_IDENTITY_PATH", None)
        if not identity_path:
            print_colored_error("No project identity is configured for wiki drafting.")
            return None

        orientation = build_repo_orientation_context(identity_path)
        prompt = (
            "You are drafting a compact INDEX.md for a project wiki. This is a curated, "
            "high-signal knowledge layer for the project below - NOT a mirror of the source tree. "
            "Use these sections as a starting structure: Overview, Architecture, Conventions, Pitfalls. "
            "Keep it concise (well under 120 lines). Capture durable, orienting knowledge only: what the "
            "project is, its major subsystems and boundaries, notable conventions, and likely pitfalls. "
            "Where useful, reference real repo-relative paths (e.g. src/...) so they can be validated later. "
            "Do not invent paths, dependencies, or facts not supported by the context. "
            "Return only the markdown for INDEX.md, with no surrounding code fences.\n\n"
            "Repository orientation context:\n"
            f"{orientation}"
        )
        try:
            llm_utils.log_helper_model_usage("wiki_init", config.MODEL)
            response = llm_utils.call_litellm_completion(
                config.MODEL,
                [
                    {
                        "role": "system",
                        "content": "You write compact, high-signal project wiki indexes.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tool_descriptions=[],
                gemini_tool_descriptions=[],
            )
        except Exception as e:
            logger.error("Failed to draft wiki INDEX with LLM: %s", e, exc_info=True)
            print_colored_error(f"Failed to draft wiki INDEX with LLM: {e}")
            return None

        content = _strip_markdown_fences(response.choices[0].message.content or "")
        if not content:
            print_colored_error("LLM-assisted wiki_init returned an empty draft.")
            return None
        if len(content) > WIKI_INIT_MAX_DRAFT_CHARACTERS:
            print_colored_error("LLM-assisted wiki_init draft is too large; keep the wiki compact.")
            return None
        if content.count("\n") + 1 > WIKI_INIT_MAX_DRAFT_LINES:
            print_colored_error("LLM-assisted wiki_init draft spans too many lines; keep the wiki compact.")
            return None
        if "#" not in content:
            print_colored_error("LLM-assisted wiki_init draft does not look like markdown.")
            return None

        draft = store_latest_wiki_init_draft(
            {
                "mode": "preview",
                "index_path": str(index_path),
                "content": content,
            }
        )
        print(content)
        print()
        print(f"Drafted INDEX.md for {index_path} (not yet written).")
        print("Review it, then run ':wiki_init apply' to write it.")
        return draft
    except Exception as e:
        logger.error("Failed to run wiki_init: %s", e, exc_info=True)
        print_colored_error(f"Failed to run wiki_init: {e}")
        return None


def wiki_lint_command(arg=None):
    """Run the configured project wiki linter.

    Args:
        arg: Optional dispatcher argument. Accepted values are ``None``,
            empty string, a help token (``help``, ``?``, ``-h``, ``--help``),
            or one of ``structural``, ``semantic``, or ``all``.

    Returns:
        dict | None: The structured wiki-lint result dict on success, or
        ``None`` when showing help, when no project wiki is configured,
        when arguments are invalid, or when an error occurs.
    """
    usage = (
        "Run the project wiki linter against the configured project wiki.\n"
        "Usage: : (or /) wiki_lint [structural|semantic|all]\n"
        "Defaults to structural mode when no argument is provided."
    )
    valid_modes = {"structural", "semantic", "all"}
    raw_arg = "" if arg is None else str(arg).strip()
    lowered_arg = raw_arg.lower()

    if lowered_arg in {"help", "?", "-h", "--help"}:
        print(usage)
        return None

    if not raw_arg:
        mode = "structural"
    elif lowered_arg in valid_modes:
        mode = lowered_arg
    else:
        print_colored_error(
            "Invalid wiki_lint mode. Use ':wiki_lint', ':wiki_lint structural', "
            "':wiki_lint semantic', or ':wiki_lint all'."
        )
        return None

    try:
        project_dir = ensure_configured_project_wiki()
        if not project_dir:
            print(
                "No configured project wiki is available. Configure a project wiki directory first, "
                "then run :wiki_lint again."
            )
            return None

        identity_path = getattr(config, "PROJECT_WIKI_IDENTITY_PATH", None)
        repo_root = Path(identity_path) if identity_path else None
        result = run_project_wiki_lint_mode(project_dir, mode, repo_root)
        print(result["report"])
        return result
    except Exception as e:
        logger.error("Failed to run project wiki linter: %s", e, exc_info=True)
        print_colored_error(f"Failed to run project wiki linter: {e}")
        return None


def _supported_wiki_fix_findings(lint_result):
    """Return supported wiki-fix findings from the latest lint result.

    Args:
        lint_result: The latest wiki lint result dict.

    Returns:
        list[dict]: Findings whose ``kind`` is currently supported by
        ``wiki_fix``.
    """
    findings = lint_result.get("findings", []) if isinstance(lint_result, dict) else []
    return [
        item
        for item in findings
        if isinstance(item, dict) and item.get("kind") in _SUPPORTED_WIKI_FIX_KINDS
    ]


def _draft_wiki_fix_preview_for_finding(lint_result, finding):
    """Draft and store one wiki-fix preview for a supported finding.

    Args:
        lint_result: The latest wiki lint result dict.
        finding: A supported finding dict from that lint result.

    Returns:
        dict | None: The stored preview result dict on success, otherwise
        ``None`` after printing a user-facing error.
    """
    project_dir = lint_result.get("project_dir", "")
    finding_id = str(finding.get("id", ""))
    page_name = str(finding.get("page", ""))
    claim = str(finding.get("claim", ""))
    path = str(finding.get("path", ""))
    evidence = str(finding.get("evidence", path))
    if not project_dir or not page_name or not claim or not path:
        print_colored_error("Selected finding does not contain enough data for wiki_fix.")
        return None

    page_path = os.path.join(project_dir, page_name)
    if not os.path.isfile(page_path):
        print_colored_error(f"Wiki page not found: {page_path}")
        return None

    original_text = Path(page_path).read_text(encoding="utf-8")
    if claim not in original_text:
        print_colored_error("Could not locate the original claim text in the wiki page.")
        return None

    prompt = (
        "You are drafting a minimal wiki update for one stale location claim. "
        "Rewrite only the specific claim text so it no longer states the stale path as fact. "
        "Do not rewrite the whole page. Do not add unrelated cleanup. "
        "Return only the replacement text for the claim, with no markdown fences.\n\n"
        f"Page: {page_name}\n"
        f"Original claim: {claim}\n"
        f"Missing path evidence: {evidence}\n"
        "Goal: replace the claim with a concise, neutral sentence that acknowledges the referenced path is stale or must be updated, without inventing a new path."
    )
    try:
        llm_utils.log_helper_model_usage("wiki_fix", config.MODEL)
        response = llm_utils.call_litellm_completion(
            config.MODEL,
            [
                {
                    "role": "system",
                    "content": "You produce minimal, localized wiki edits only.",
                },
                {"role": "user", "content": prompt},
            ],
            tool_descriptions=[],
            gemini_tool_descriptions=[],
        )
    except Exception as e:
        logger.error("Failed to draft wiki fix with LLM: %s", e, exc_info=True)
        print_colored_error(f"Failed to draft wiki fix with LLM: {e}")
        return None

    replacement = (response.choices[0].message.content or "").strip()
    if not replacement:
        print_colored_error("LLM-assisted wiki_fix returned an empty replacement.")
        return None
    if len(replacement) > WIKI_FIX_MAX_REPLACEMENT_CHARACTERS:
        print_colored_error("LLM-assisted wiki_fix replacement is too large.")
        return None
    if replacement.count("\n") + 1 > WIKI_FIX_MAX_REPLACEMENT_LINES:
        print_colored_error("LLM-assisted wiki_fix replacement spans too many lines.")
        return None
    if claim == replacement:
        print_colored_error("LLM-assisted wiki_fix did not change the targeted claim.")
        return None

    updated_text = original_text.replace(claim, replacement, 1)
    diff_text = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            updated_text.splitlines(keepends=True),
            fromfile=f"a/{page_path}",
            tofile=f"b/{page_path}",
        )
    )
    if wiki_fix_diff_line_count(diff_text) > WIKI_FIX_MAX_DIFF_LINES:
        print_colored_error("LLM-assisted wiki_fix diff footprint is too large.")
        return None

    preview_result = store_latest_wiki_fix_preview(
        {
            "finding_id": finding_id,
            "page": page_name,
            "mode": "preview",
            "fix_mode": "llm",
            "diff": diff_text,
            "updated_text": updated_text,
            "replacement": replacement,
            "page_path": page_path,
            "claim": claim,
        }
    )
    print(diff_text)
    return preview_result


def _apply_stored_wiki_fix_preview_for_finding(lint_result, finding):
    """Apply one stored wiki-fix preview for a supported finding.

    Args:
        lint_result: The latest wiki lint result dict.
        finding: A supported finding dict from that lint result.

    Returns:
        dict | None: The apply result dict on success, otherwise ``None`` after
        printing a user-facing error.
    """
    finding_id = str(finding.get("id", ""))
    page_name = str(finding.get("page", ""))
    claim = str(finding.get("claim", ""))
    project_dir = lint_result.get("project_dir", "")
    path = str(finding.get("path", ""))
    if not project_dir or not page_name or not claim or not path:
        print_colored_error("Selected finding does not contain enough data for wiki_fix.")
        return None

    page_path = os.path.join(project_dir, page_name)
    if not os.path.isfile(page_path):
        print_colored_error(f"Wiki page not found: {page_path}")
        return None

    original_text = Path(page_path).read_text(encoding="utf-8")
    preview_result = latest_wiki_fix_preview(finding_id)
    if not preview_result:
        print_colored_error(
            "No stored wiki_fix preview is available for that finding. Run ':wiki_fix llm <finding_id>' first."
        )
        return None

    preview_page = str(preview_result.get("page", ""))
    preview_claim = str(preview_result.get("claim", ""))
    preview_updated_text = str(preview_result.get("updated_text", ""))
    preview_diff = str(preview_result.get("diff", ""))
    preview_replacement = str(preview_result.get("replacement", ""))
    preview_page_path = str(preview_result.get("page_path", page_path))
    if preview_page != page_name or preview_claim != claim or not preview_updated_text or not preview_diff:
        print_colored_error(
            "Stored wiki_fix preview is incomplete or no longer matches the selected finding. Run ':wiki_fix llm <finding_id>' again."
        )
        return None
    if original_text == preview_updated_text:
        print_colored_error("The wiki page already matches the stored wiki_fix preview.")
        return None
    expected_original_text = original_text.replace(preview_replacement, claim, 1)
    if expected_original_text != original_text and claim not in original_text:
        print_colored_error(
            "The wiki page changed after preview generation. Run ':wiki_fix llm <finding_id>' again before applying."
        )
        return None

    Path(preview_page_path).write_text(preview_updated_text, encoding="utf-8")
    print(preview_diff)
    print(f"Applied wiki fix to {preview_page_path}")
    return {
        "finding_id": finding_id,
        "page": page_name,
        "mode": "apply",
        "fix_mode": "llm",
        "diff": preview_diff,
        "updated_text": preview_updated_text,
        "replacement": preview_replacement,
        "page_path": preview_page_path,
    }


def wiki_fix_command(arg=None):
    """Draft or apply LLM-assisted wiki fixes for stored lint findings.

    Args:
        arg: Required argument string in one of the forms
            ``llm <finding_id>``, ``apply <finding_id>``, ``llm_all``,
            ``apply_all``, ``auto_all``, or a help token.

    Returns:
        dict | None: A preview or apply result for single-finding commands, or
        a summary dict with counts and per-finding results for ``llm_all``,
        ``apply_all``, and ``auto_all``. Returns ``None`` when showing help,
        when no latest lint result is available, when arguments are invalid,
        or when a guardrail prevents the requested operation.
    """
    usage = (
        "Draft or apply an LLM-assisted wiki fix for findings from the latest wiki lint run.\n"
        "Usage: : (or /) wiki_fix llm <finding_id>\n"
        "       : (or /) wiki_fix apply <finding_id>\n"
        "       : (or /) wiki_fix llm_all\n"
        "       : (or /) wiki_fix apply_all\n"
        "       : (or /) wiki_fix auto_all\n"
        "Currently supports semantic stale location, authority, workflow, and ownership claims. "
        "'llm' previews a diff, 'apply' saves a stored preview for one finding, 'llm_all' previews "
        "all supported findings, 'apply_all' applies stored previews for all supported findings, "
        "and 'auto_all' previews then applies all supported findings in one explicit batch command."
    )
    raw_arg = "" if arg is None else str(arg).strip()
    lowered_arg = raw_arg.lower()
    if lowered_arg in {"help", "?", "-h", "--help"} or not raw_arg:
        print(usage)
        return None

    lint_result = latest_wiki_lint_result()
    if not lint_result:
        print("No stored wiki lint result is available. Run :wiki_lint first.")
        return None

    findings = lint_result.get("findings", [])
    supported_findings = _supported_wiki_fix_findings(lint_result)

    if lowered_arg == "llm_all":
        preview_results = []
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("kind") not in _SUPPORTED_WIKI_FIX_KINDS:
                continue
            preview_result = _draft_wiki_fix_preview_for_finding(lint_result, finding)
            if preview_result is None:
                return None
            preview_results.append(preview_result)
        return {
            "mode": "preview_all",
            "fix_mode": "llm",
            "supported_count": len(supported_findings),
            "previewed_count": len(preview_results),
            "results": preview_results,
        }

    if lowered_arg == "auto_all":
        preview_all_result = wiki_fix_command("llm_all")
        if preview_all_result is None:
            return None
        apply_all_result = wiki_fix_command("apply_all")
        if apply_all_result is None:
            return None
        return {
            "mode": "auto_all",
            "fix_mode": "llm",
            "supported_count": len(supported_findings),
            "previewed_count": preview_all_result.get("previewed_count", 0),
            "applied_count": apply_all_result.get("applied_count", 0),
            "preview_results": preview_all_result.get("results", []),
            "apply_results": apply_all_result.get("results", []),
        }

    if lowered_arg == "apply_all":
        missing_preview_finding_id = None
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("kind") not in _SUPPORTED_WIKI_FIX_KINDS:
                continue
            finding_id = str(finding.get("id", ""))
            if not latest_wiki_fix_preview(finding_id):
                missing_preview_finding_id = finding_id
                break
        if missing_preview_finding_id is not None:
            print_colored_error(
                "No stored wiki_fix preview is available for supported finding "
                f"{missing_preview_finding_id}. Run ':wiki_fix llm_all' first."
            )
            return None

        apply_results = []
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("kind") not in _SUPPORTED_WIKI_FIX_KINDS:
                continue
            apply_result = _apply_stored_wiki_fix_preview_for_finding(lint_result, finding)
            if apply_result is None:
                return None
            apply_results.append(apply_result)
        return {
            "mode": "apply_all",
            "fix_mode": "llm",
            "supported_count": len(supported_findings),
            "applied_count": len(apply_results),
            "results": apply_results,
        }

    parts = raw_arg.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() not in {"llm", "apply"}:
        print_colored_error(
            "wiki_fix requires one of ':wiki_fix llm <finding_id>', ':wiki_fix apply <finding_id>', "
            "':wiki_fix llm_all', ':wiki_fix apply_all', or ':wiki_fix auto_all'."
        )
        return None
    action = parts[0].lower()
    finding_id = parts[1].strip()
    if not finding_id:
        print_colored_error(f"wiki_fix requires a finding id after '{action}'.")
        return None

    finding = next(
        (
            item
            for item in findings
            if isinstance(item, dict) and str(item.get("id", "")) == finding_id
        ),
        None,
    )
    if finding is None:
        print_colored_error(f"Unknown wiki lint finding id: {finding_id}")
        return None

    if finding.get("kind") not in _SUPPORTED_WIKI_FIX_KINDS:
        print_colored_error(
            "wiki_fix currently supports only semantic_stale_location_claim, semantic_stale_authority_claim, semantic_stale_workflow_claim, and semantic_stale_ownership_claim findings."
        )
        return None

    if action == "llm":
        return _draft_wiki_fix_preview_for_finding(lint_result, finding)

    return _apply_stored_wiki_fix_preview_for_finding(lint_result, finding)
