import difflib
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict

import appdirs
import litellm
from colored import attr, fg
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import BashLexer, MarkdownLexer

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
from monitor.lib.built_ins_history_utils import (
    _format_elapsed,
    cost_debug_command,
    dump_history_command,
    dump_metrics_command,
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
    latest_wiki_fix_preview,
    store_latest_wiki_fix_preview,
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
from monitor.lib.monitor_wiki import ensure_configured_project_wiki
from monitor.lib.monitor_wiki_linter import latest_wiki_lint_result, run_project_wiki_lint_mode
from monitor.lib.preferences import open_preferences_editor
from monitor.lib.summarizers import summarize_conversation_for_linkedin
from monitor.lib.summarizers import summarize_conversation_for_twitch
from monitor.lib.system_prompt import build_system_prompt, clear_project_instructions_cache
from monitor.lib.tool_loading import list_tools

reasoning_command.__globals__["config"] = config
llm_command.__globals__["config"] = config
ttl_command.__globals__["config"] = config
max_tokens_command.__globals__["config"] = config

logger = logging.getLogger(__name__)

def print_tools_command(arg=None):
    from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, TOOL_STATE

    # Debug logging: log types and (truncated) contents of TOOL_DESCRIPTIONS and TOOL_STATE.
    # Helper to truncate large structures for preview.
    def _truncate_repr(obj, maxlen=500):
        try:
            rep = repr(obj)
        except Exception as e:
            rep = f"repr-failed({e})"
        if len(rep) > maxlen:
            return rep[:maxlen] + "... [truncated]"
        return rep

    # TOOL_DESCRIPTIONS type and truncated content
    logger.debug(f"TOOL_DESCRIPTIONS type: {type(TOOL_DESCRIPTIONS)} - preview: {_truncate_repr(TOOL_DESCRIPTIONS)}")
    if not isinstance(TOOL_DESCRIPTIONS, list):
        logger.warning("TOOL_DESCRIPTIONS is not a list!")

    # TOOL_STATE type and truncated content
    logger.debug(f"TOOL_STATE type: {type(TOOL_STATE)} - preview: {_truncate_repr(TOOL_STATE)}")
    if not isinstance(TOOL_STATE, dict):
        logger.warning("TOOL_STATE is not a dict!")

    tools = list_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
    logger.debug(f"tools after list_tools() type: {type(tools)} - preview: {_truncate_repr(tools)}")
    if not isinstance(tools, dict):
        logger.warning("tools is not a dict after list_tools()!")

    for name, info in tools.items():
        print(f"Tool: {name}")
        print(f"  Description: {info['description']}")
        print(f"  Active: {info['active']}")
        print("-" * 40)


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

        result = run_project_wiki_lint_mode(project_dir, mode)
        print(result["report"])
        return result
    except Exception as e:
        logger.error("Failed to run project wiki linter: %s", e, exc_info=True)
        print_colored_error(f"Failed to run project wiki linter: {e}")
        return None


def wiki_fix_command(arg=None):
    """Draft or apply an LLM-assisted wiki fix for a stored lint finding.

    Args:
        arg: Required argument string in the form ``llm <finding_id>`` or
            ``apply <finding_id>``, or a help token.

    Returns:
        dict | None: A preview or apply result containing the finding id, page,
        and diff when a supported fix can be drafted or written, otherwise
        ``None``.
    """
    usage = (
        "Draft or apply an LLM-assisted wiki fix for a finding from the latest wiki lint run.\n"
        "Usage: : (or /) wiki_fix llm <finding_id>\n"
        "       : (or /) wiki_fix apply <finding_id>\n"
        "Currently supports semantic stale location, authority, and workflow claims. 'llm' previews a diff and 'apply' saves the drafted change to disk."
    )
    raw_arg = "" if arg is None else str(arg).strip()
    lowered_arg = raw_arg.lower()
    if lowered_arg in {"help", "?", "-h", "--help"} or not raw_arg:
        print(usage)
        return None

    parts = raw_arg.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() not in {"llm", "apply"}:
        print_colored_error(
            "wiki_fix requires the form ':wiki_fix llm <finding_id>' or ':wiki_fix apply <finding_id>'."
        )
        return None
    action = parts[0].lower()
    finding_id = parts[1].strip()
    if not finding_id:
        print_colored_error(f"wiki_fix requires a finding id after '{action}'.")
        return None

    lint_result = latest_wiki_lint_result()
    if not lint_result:
        print("No stored wiki lint result is available. Run :wiki_lint first.")
        return None

    findings = lint_result.get("findings", [])
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

    if finding.get("kind") not in {
        "semantic_stale_location_claim",
        "semantic_stale_authority_claim",
        "semantic_stale_workflow_claim",
    }:
        print_colored_error(
            "wiki_fix currently supports only semantic_stale_location_claim, semantic_stale_authority_claim, and semantic_stale_workflow_claim findings."
        )
        return None

    project_dir = lint_result.get("project_dir", "")
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

    if action == "llm":
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
            response = litellm.completion(
                model=config.MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You produce minimal, localized wiki edits only.",
                    },
                    {"role": "user", "content": prompt},
                ],
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
