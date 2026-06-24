"""Handles macro orchestration, configuration, global macro state, and all CLI/user commands. Calls stateless helpers from macro_utils.

TRUST MODEL
-----------
The macros subsystem supports Tcl evaluation in both `{{tcl ...}}` macro
expressions and macro values that begin with bare `tcl ...`. Both forms
evaluate arbitrary Tcl code in a tkinter.Tcl() interpreter on the host. Tcl is
*not* a sandboxed templating language; it can `exec` shell commands,
read/write files, open sockets, and read environment variables.

Implications:
- ``macros.json`` is effectively executable code. Treat it with the same trust
  as a shell script you would source. Do not import macros files from
  untrusted sources, do not sync them across machines without review, and do
  not accept Tcl macros from network input.
- Macros added at runtime via ``<key=value`` (``add_macro_definition``) are
  also unsandboxed. Anything the user types after ``<key=`` becomes
  executable on expansion if the resulting macro body is recognized as Tcl,
  including either ``{{tcl ...}}`` or bare ``tcl ...`` forms.
- PRIVATE_MACRO_VALUES in this module are the only macros that cannot be
  overridden by user input (precedence: PUBLIC < file < EPHEMERAL < PRIVATE).

If you ever need to evaluate macros from a less-trusted source, the Tcl
expansion path in ``macro_utils.tcl_macro_expand`` is the boundary to gate.
"""

import logging
import os
import subprocess
from textwrap import dedent

from monitor import config

from monitor.lib.macro_utils import (
    load_additional_macro_metadata,
    load_additional_macros,
    update_macros,
)
from monitor.lib.colors import magenta, red, reset, yellow

MACRO_VALUES = {}

logger = logging.getLogger(__name__)

# When adding macros via '<key=value' the macros are stored in EPHEMERAL_MACRO_VALUES
# and are destroyed when monitor exits. If you want macros to persist, use the
# :edit_macros command
EPHEMERAL_MACRO_VALUES = {}

# Initialize macro values dictionary with hardcoded values
# These are not visible dumping the macros via the 'macros' built in command.
PRIVATE_MACRO_VALUES = {
    "system?": "Are you awake and operational?",
    "memories?": "What are your memories?",
    "purpose?": "What is your purpose?",
    "self_test": "what is the weather in san diego, ca in F? {{purpose?}} {{memories?}}",
}

PRIVATE_MACRO_METADATA = {
    "system?": {
        "title": "System prompt check",
        "description": "Internal prompt used to verify the assistant is responsive.",
        "group": "built_in_internal",
    },
    "memories?": {
        "title": "Memory prompt check",
        "description": "Internal prompt used to inspect the assistant's memories.",
        "group": "built_in_internal",
    },
    "purpose?": {
        "title": "Purpose prompt check",
        "description": "Internal prompt used to ask the assistant about its purpose.",
        "group": "built_in_internal",
    },
    "self_test": {
        "title": "Internal self test",
        "description": "Internal macro that chains built-in prompts for a quick self test.",
        "group": "built_in_internal",
    },
}

# Useful macros, these are visible when dumping macros via the 'macros' built in command.
PUBLIC_MACRO_VALUES = {
    "do_diff": "Examine the files that have been modified, using the perform_git_diff tool",
    "create_git_entry": dedent("""
        Write a commit message that strictly follows this specification.

        Requirements:

        Subject:
        - Separate the commit message into a Subject and Body
        - Capitalize the Subject
        - Keep the Subject at 50 characters or fewer
        - Do not end the Subject with a period
        - Start the Subject with the appropriate leading verb
        - Use imperative mood
        - Describe what changed, not why or how

        Allowed leading verbs:
        - Add: create a feature, test, dependency, etc.
        - Remove: remove a feature, test, dependency, etc.
        - Fix: fix a bug, style violation, typo, etc.
        - Upgrade: upgrade a dependency; format as "Upgrade DEP_NAME to VERSION"
        - Refactor: design-only change; behavior should not change
        - Reformat: formatting-only change
        - Start: begin doing something, such as enabling a toggle or flag
        - Stop: end doing something, such as disabling a toggle or flag
        - Document: documentation or comment change
        - Make: build process or tooling change
        - Bump: increase the project version
        - Rearrange: purely rearrange layout or UI
        - Redraw: change a visual asset
        - Reword: purely textual change
        - Revert: purely the result of git revert
        - Import: purely the result of importing into Git LFS

        Body:
        - A Body is required unless the change is purely cosmetic or extremely minor
        - Include a Body for all non-trivial changes
        - Place exactly one blank line after the Subject
        - Hard-wrap body lines at 72 characters, except URLs
        - Explain what changed and why, not how
        - Provide enough context for a reviewer or later reader to understand the intent and impact

        The body is read by a tool that builds contextual understanding of the development process, so it must provide comprehensive context.

        Body content by change type:

        Bug fix — explain:
        - what was broken
        - what should happen instead
        - why the correction matters to users or the system
        - what changed from the user's perspective
        - why that behavior is desirable or necessary
        - any product or context motivation
        Implementation details are secondary unless they explain a non-obvious constraint or risk.

        New feature — explain:
        - what new capability exists for users
        - why it was added
        Keep implementation details out unless they matter for reviewers, rollout, or risk.

        Refactor — explain:
        - what design or maintenance issue is being addressed
        - why the change helps
        - whether behavior is intentionally unchanged (usually it is)
        Avoid generic "cleanup" framing or listing moved methods unless that context matters.

        Return only the commit message text.
    """).strip(),
    "rank_examine": "Rank what to examine next",
    "diff": "{{do_diff}} {{create_git_entry}}",
    "diff_previous": "Examine the files that have been modified since the last commit, using the perform_git_diff_previous tool, so that I can see the difference between the current commit and its parent previous commit. Tell me the results of the overall change.",
    "xdiff": "Use the git show tool to examine the source code changes for the following hash or branch name: ",
    "plan": "Give me a step by step plan",
    "wdyt": "Don't change any code. Tell me what do you think",
}

PUBLIC_MACRO_METADATA = {
    "do_diff": {
        "title": "Diff current changes",
        "description": "Ask the assistant to inspect the files modified in the current working tree.",
        "group": "built_in_general",
    },
    "create_git_entry": {
        "title": "Write git commit message",
        "description": "Generate a concise commit title and a detailed wrapped commit body.",
        "group": "built_in_general",
    },
    "rank_examine": {
        "title": "Rank next examination target",
        "description": "Ask the assistant to prioritize what should be examined next.",
        "group": "built_in_general",
    },
    "diff": {
        "title": "Diff plus commit entry",
        "description": "Run the diff review flow together with commit message drafting guidance.",
        "group": "built_in_general",
    },
    "diff_previous": {
        "title": "Diff previous commit",
        "description": "Inspect changes between the current commit and its parent commit.",
        "group": "built_in_general",
    },
    "xdiff": {
        "title": "Show diff for revision",
        "description": "Inspect source changes for a supplied commit hash or branch name.",
        "group": "built_in_general",
    },
    "plan": {
        "title": "Step-by-step plan",
        "description": "Ask the assistant to produce a step-by-step plan.",
        "group": "built_in_general",
    },
    "wdyt": {
        "title": "What do you think",
        "description": "Request feedback without changing any code.",
        "group": "built_in_general",
    },
}

BUILT_IN_GROUP_METADATA = {
    "built_in_general": {
        "title": "Built-in macros",
        "description": "Macros that ship with the application and are visible in normal macro listings.",
        "order": 100,
    },
    "built_in_internal": {
        "title": "Built-in internal macros",
        "description": "Internal macros reserved for runtime behavior and excluded from normal display.",
        "order": 900,
    },
    "runtime": {
        "title": "Runtime macros",
        "description": "Macros added during the current session with the <key=value syntax.",
        "order": 300,
    },
    "file": {
        "title": "Macros file",
        "description": "Persistent macros loaded from the configured macros file.",
        "order": 200,
    },
}


def _normalize_macro_metadata(name, metadata=None, default_group="file"):
    """Normalize metadata for a macro entry.

    Invalid non-dictionary metadata values are ignored so malformed nested
    entries in ``_macro_meta`` cannot break macro display.

    Args:
        name (str): Macro name.
        metadata (dict | None): Raw metadata dictionary for the macro.
        default_group (str): Group identifier to use when metadata omits one.

    Returns:
        dict: Normalized metadata containing ``title``, ``description``,
        ``usage``, and ``group`` keys.
    """
    if not isinstance(metadata, dict):
        metadata = {}
    title = metadata.get("title") or name
    description = metadata.get("description") or ""
    usage = metadata.get("usage") or ""
    group = metadata.get("group") or default_group
    return {
        "title": title,
        "description": description,
        "usage": usage,
        "group": group,
    }


def _normalize_group_metadata(group_name, metadata=None, default_order=500):
    """Normalize metadata for a group entry.

    Invalid non-dictionary metadata values are ignored so malformed nested
    entries in ``_groups`` cannot break macro display.

    Args:
        group_name (str): Group identifier.
        metadata (dict | None): Raw metadata dictionary for the group.
        default_order (int): Sort order to use when metadata omits one.

    Returns:
        dict: Normalized metadata containing ``title``, ``description``, and
        ``order`` keys.
    """
    if not isinstance(metadata, dict):
        metadata = {}
    title = metadata.get("title") or group_name.replace("_", " ").title()
    description = metadata.get("description") or ""
    order = metadata.get("order", default_order)
    if not isinstance(order, (int, float)):
        order = default_order
    return {
        "title": title,
        "description": description,
        "order": order,
    }


def _build_visible_macro_catalog():
    """Build the visible macro catalog using display precedence rules.

    Visible macro display follows precedence ``public < file < ephemeral`` so
    later sources replace earlier entries with the same macro name. Private
    macros are excluded from the returned catalog.

    Returns:
        tuple[list[dict], dict]: A tuple containing a list of visible macro
        entries and normalized group metadata keyed by group name.
    """
    file_macros = load_additional_macros(config.MACRO_FILE_PATH)
    file_metadata = load_additional_macro_metadata(config.MACRO_FILE_PATH)

    group_metadata = {
        group_name: _normalize_group_metadata(group_name, metadata)
        for group_name, metadata in BUILT_IN_GROUP_METADATA.items()
    }
    for group_name, metadata in file_metadata.get("groups", {}).items():
        group_metadata[group_name] = _normalize_group_metadata(
            group_name,
            metadata,
            default_order=group_metadata.get(group_name, {}).get("order", 500),
        )

    visible_macros = {}

    sources = [
        ("public", PUBLIC_MACRO_VALUES, PUBLIC_MACRO_METADATA, "built_in_general"),
        ("file", file_macros, file_metadata.get("macro_meta", {}), "file"),
        ("ephemeral", EPHEMERAL_MACRO_VALUES, {}, "runtime"),
    ]

    for source_label, macro_values, macro_metadata, default_group in sources:
        for name, value in macro_values.items():
            normalized_metadata = _normalize_macro_metadata(
                name,
                macro_metadata.get(name),
                default_group=default_group,
            )
            group_name = normalized_metadata["group"]
            if group_name not in group_metadata:
                group_metadata[group_name] = _normalize_group_metadata(group_name)
            visible_macros[name] = {
                "name": name,
                "value": value,
                "title": normalized_metadata["title"],
                "description": normalized_metadata["description"],
                "usage": normalized_metadata["usage"],
                "group": group_name,
                "source": source_label,
            }

    catalog = sorted(
        visible_macros.values(),
        key=lambda entry: (
            group_metadata[entry["group"]]["order"],
            group_metadata[entry["group"]]["title"].lower(),
            entry["name"].lower(),
        ),
    )
    return catalog, group_metadata


def _render_grouped_macro_catalog(catalog, group_metadata):
    """Render the visible macro catalog as grouped plain text.

    Args:
        catalog (list[dict]): Visible macro entries to render.
        group_metadata (dict): Normalized group metadata keyed by group name.

    Returns:
        str: Grouped text suitable for paging or direct printing.
    """
    if not catalog:
        return "No visible macros are currently defined."

    source_labels = {
        "public": "built-in",
        "file": "file",
        "ephemeral": "runtime",
    }

    lines = []
    current_group = None

    for entry in catalog:
        group_name = entry["group"]
        if group_name != current_group:
            if lines:
                lines.append("")
            group_info = group_metadata[group_name]
            lines.append(group_info["title"])
            lines.append("-" * len(group_info["title"]))
            if group_info["description"]:
                lines.append(group_info["description"])
                lines.append("")
            current_group = group_name

        source_label = source_labels.get(entry["source"], entry["source"])
        lines.append(f"{yellow}{entry['name']}{reset}")
        lines.append(f"  Source: {source_label}")
        if entry["title"] and entry["title"] != entry["name"]:
            lines.append(f"  Title: {entry['title']}")
        if entry["description"]:
            lines.append(f"  Description: {entry['description']}")
        if entry["usage"]:
            lines.append(f"  Usage: {magenta}{entry['usage']}{reset}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def configure_macros():
    """Load, update, and configure all macro dictionaries into global MACRO_VALUES.

    MAC-4: precedence order (lowest → highest), since dict.update is last-wins:
      1. PUBLIC_MACRO_VALUES — hardcoded built-in defaults
      2. additional_macros (file-based) — user persistent overrides
      3. EPHEMERAL_MACRO_VALUES — runtime-added by user via `<key=value`;
         must outrank file so a reload doesn't clobber the user's current-session
         redefinitions
      4. PRIVATE_MACRO_VALUES — hardcoded internal macros that must not be
         user-overridable

    Returns:
        None
    """
    additional_macros = load_additional_macros(config.MACRO_FILE_PATH)
    update_macros(MACRO_VALUES, PUBLIC_MACRO_VALUES)
    update_macros(MACRO_VALUES, additional_macros)
    update_macros(MACRO_VALUES, EPHEMERAL_MACRO_VALUES)
    update_macros(MACRO_VALUES, PRIVATE_MACRO_VALUES)


def print_macros(arg=None):
    """Display visible macros grouped by metadata using a paginated view.

    Renders public, file-based, and ephemeral macros grouped by metadata and
    displays them to the user. Pipes through a pager (Unix less-like) if
    available, falls back to print.

    Args:
        arg: Optional; Unused, maintained for CLI handler compatibility.

    Returns:
        None
    """
    _ = arg
    catalog, group_metadata = _build_visible_macro_catalog()
    combined_output = _render_grouped_macro_catalog(catalog, group_metadata)

    _unset = object()
    previous_less = os.environ.get("LESS", _unset)
    os.environ["LESS"] = "-R"
    try:
        import pydoc

        pydoc.pager(combined_output)
    except Exception as exc:  # pragma: no cover
        print(combined_output)
        logger.warning("pydoc.pager failed: %s; falling back to print.", exc)
    finally:
        if previous_less is _unset:
            os.environ.pop("LESS", None)
        else:
            os.environ["LESS"] = previous_less


def add_macro_definition(user_input):
    """Handles addition of ephemeral macros at runtime via user input.

    Updates the ephemeral macros dictionary and global MACRO_VALUES in-place to include
    new macro definition.

    Args:
        user_input (str): User input string in the form '<key=expansion'

    Returns:
        bool: True if addition succeeded, False if parsing failed.
    """
    try:
        key, value = user_input[1:].split("=", 1)
        key, value = key.strip(), value.strip()
        EPHEMERAL_MACRO_VALUES[key] = value
        update_macros(MACRO_VALUES, EPHEMERAL_MACRO_VALUES)
        print(f"{yellow}Added to macro_values: '{key}': '{value}'{reset}\n")
        logger.info("Macro added: {} = {}".format(key, value))
        return True
    except ValueError:
        logger.error(
            "Error in macro formatting. Expected format: '<key=expansion'"
        )
        return False


def open_macros_editor():
    """Open the user's editor to edit the macros file specified by config.MACRO_FILE_PATH.

    Launches the editor specified by the $EDITOR environment variable or falls back to 'nano' or 'vi'
    to allow the user to edit the macro file directly. If the macro file does not exist, it is created
    as an empty file before launching the editor.

    Returns:
        None

    Raises:
        OSError: If there is a problem launching the editor or saving the file.
    """
    macros_file_path = config.MACRO_FILE_PATH

    try:
        # Ensure parent directory exists before creating or editing the file
        parent_dir = os.path.dirname(macros_file_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Create the file if it does not exist
        if not os.path.exists(macros_file_path):
            with open(macros_file_path, "a", encoding="utf-8"):
                pass  # Create empty file

        editor = os.environ.get("EDITOR")
        editors_tried = []
        if editor:
            editors_to_try = [editor]
        else:
            editors_to_try = ["vim", "nano", "vi"]

        for candidate in editors_to_try:
            try:
                print(f"Opening macros file in: {candidate}")
                subprocess.run([candidate, macros_file_path], check=True)
                print(f"{yellow}Macros edited successfully. Reload macros with ':reload_macros' or restart the app to apply changes.{reset}")
                return
            except FileNotFoundError:
                editors_tried.append(candidate)
                continue
            except Exception as exc:
                error_msg = f"{red}Failed to open macros file with {candidate}: {exc}{reset}"
                print(error_msg)
                logger.error(error_msg, exc_info=True)
                editors_tried.append(candidate)
                continue

        # All editors failed, print and log error message as required before raising
        editors_to_report = editors_to_try if editors_tried == editors_to_try else editors_tried
        editor_list_str = 'nano, vim, vi'
        error_msg = f"Could not find a suitable editor (tried {editor_list_str}). Please set the $EDITOR environment variable."
        print(f"{red}{error_msg}{reset}")
        logger.error(error_msg)
        raise OSError(f"No suitable editor found or failed to launch after trying: {', '.join(editors_tried)}. Please set the $EDITOR environment variable.")
    except Exception as exc:
        error_msg = f"{red}Failed to open macros file for editing: {exc}{reset}"
        print(error_msg)
        logger.error(error_msg, exc_info=True)
