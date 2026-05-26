import logging

from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.filters import Condition

from monitor.lib.voice_to_text import VoiceToText

LOGGER = logging.getLogger(__name__)


def _print_above_prompt(text):
    """Print ``text`` above the running prompt without corrupting the UI.

    Wraps prompt-toolkit's ``run_in_terminal`` so the prompt is properly hidden
    while we write, then restored. Calling ``event.app.print_text`` directly
    from a key handler is documented to "destroy the UI" — the message appears
    but the prompt's redraw state stays half-broken until something else (an
    Enter submission, a resize) forces a refresh.
    """
    def do_print():
        print(text, end="")
    run_in_terminal(do_print)

USER_FUNCTION_KEYS = tuple(f"f{i}" for i in range(1, 9))

VOICE_TO_TEXT = None
FUNCTION_KEY_INSERTIONS = {}
FUNCTION_KEY_GROUPS = {}
ACTIVE_FUNCTION_KEY_GROUP = None
ACTIVE_FUNCTION_KEY_MAPPING = {}
FUNCTION_KEY_SELECTOR_STATE = {
    "open": False,
    "preview_group": None,
}


def configure_voice_to_text():
    """Initialize the shared voice-to-text instance."""
    global VOICE_TO_TEXT
    VOICE_TO_TEXT = VoiceToText()  # Configure with device/model as needed


def _normalize_function_key_groups(function_key_insertions):
    """Normalize the validated grouped function-key config.

    Accepts the spec shape only: a top-level dict whose keys are group names
    and whose values are dicts mapping F-key names (F1-F8) to entries with
    ``text`` and ``description`` fields. Pre-validated by
    ``monitor.function_keys.validate_function_keys_config`` in the production
    path; this normalizer also tolerates direct in-process callers by silently
    dropping anything outside F1-F8 or missing ``text``.
    """
    groups = {}
    if not isinstance(function_key_insertions, dict):
        return groups

    for group_name, group_mapping in function_key_insertions.items():
        if not isinstance(group_name, str):
            continue
        normalized_group_name = group_name.strip()
        if not normalized_group_name or not isinstance(group_mapping, dict):
            continue

        normalized_group = {}
        for key, value in group_mapping.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.lower()
            if normalized_key not in USER_FUNCTION_KEYS:
                continue
            if not isinstance(value, dict):
                continue
            text = value.get("text")
            if not isinstance(text, str) or not text:
                continue
            description = value.get("description")
            if not isinstance(description, str):
                description = ""
            normalized_group[normalized_key] = {"text": text, "description": description}

        if normalized_group:
            groups[normalized_group_name] = normalized_group

    return groups


SELECTOR_HINT = "TAB to cycle. F12 to choose. ESC to cancel."


def _format_function_key_selector_output(group_name):
    """Format the current function-key selector group and entries for display."""
    if group_name not in FUNCTION_KEY_GROUPS:
        return "Function key selector: no active group\n"

    lines = [f"Function key selector: {group_name}"]
    for entry in get_function_key_selector_entries(group_name):
        lines.append(f"{entry['key']}: {entry['description']}")
    return "\n".join(lines) + "\n"


def _format_function_keys_quick_reference():
    """Format every configured group and its bindings as a single reference block."""
    if not FUNCTION_KEY_GROUPS:
        return "Function keys: no groups configured\n"

    lines = ["Function keys:"]
    for group_name in FUNCTION_KEY_GROUPS:
        marker = " (active)" if group_name == ACTIVE_FUNCTION_KEY_GROUP else ""
        lines.append(f"  [{group_name}]{marker}")
        for entry in get_function_key_selector_entries(group_name):
            lines.append(f"    {entry['key']}: {entry['description']}")
    lines.append("")
    lines.append(SELECTOR_HINT)
    return "\n".join(lines) + "\n"


def _print_function_keys_quick_reference():
    """Render the full multi-group reference + hint on selector open."""
    _print_above_prompt(_format_function_keys_quick_reference())
    LOGGER.info("function key quick reference displayed")


def _print_function_key_selector_output(group_name):
    """Print the current function-key selector contents above the prompt."""
    _print_above_prompt(_format_function_key_selector_output(group_name))
    LOGGER.info("function key selector displayed for group=%s", group_name)


def _set_active_function_key_group(group_name):
    """Set the active function-key group and runtime insertion mapping."""
    global ACTIVE_FUNCTION_KEY_GROUP
    global ACTIVE_FUNCTION_KEY_MAPPING
    global FUNCTION_KEY_INSERTIONS

    if group_name not in FUNCTION_KEY_GROUPS:
        ACTIVE_FUNCTION_KEY_GROUP = None
        ACTIVE_FUNCTION_KEY_MAPPING = {}
        FUNCTION_KEY_INSERTIONS = {}
        FUNCTION_KEY_SELECTOR_STATE["preview_group"] = None
        return False

    ACTIVE_FUNCTION_KEY_GROUP = group_name
    ACTIVE_FUNCTION_KEY_MAPPING = FUNCTION_KEY_GROUPS[group_name]
    FUNCTION_KEY_INSERTIONS = {
        key_name: entry["text"] for key_name, entry in ACTIVE_FUNCTION_KEY_MAPPING.items()
    }
    FUNCTION_KEY_SELECTOR_STATE["preview_group"] = group_name
    return True


def configure_function_key_insertions(function_key_insertions):
    """Store validated grouped function-key text insertions.

    Args:
        function_key_insertions: Top-level dict of group names to F-key mappings,
            as produced by ``validate_function_keys_config``. The first group in
            iteration order is activated; selection is session-local per spec.
    """
    global FUNCTION_KEY_GROUPS
    global FUNCTION_KEY_INSERTIONS
    global ACTIVE_FUNCTION_KEY_GROUP
    global ACTIVE_FUNCTION_KEY_MAPPING

    FUNCTION_KEY_GROUPS = _normalize_function_key_groups(function_key_insertions)
    FUNCTION_KEY_INSERTIONS = {}
    FUNCTION_KEY_SELECTOR_STATE["open"] = False
    FUNCTION_KEY_SELECTOR_STATE["preview_group"] = None

    if not FUNCTION_KEY_GROUPS:
        ACTIVE_FUNCTION_KEY_GROUP = None
        ACTIVE_FUNCTION_KEY_MAPPING = {}
        LOGGER.info("no valid function key groups configured")
        return

    first_group = next(iter(FUNCTION_KEY_GROUPS))
    _set_active_function_key_group(first_group)
    LOGGER.info(
        "loaded %d function key group(s); active group=%s",
        len(FUNCTION_KEY_GROUPS),
        ACTIVE_FUNCTION_KEY_GROUP,
    )


def switch_active_function_key_group(group_name):
    """Switch the active function-key group.

    Args:
        group_name: The configured group name to activate.

    Returns:
        bool: True when the group was activated, otherwise False.
    """
    if group_name not in FUNCTION_KEY_GROUPS:
        LOGGER.info("function key group not found: %s", group_name)
        return False

    _set_active_function_key_group(group_name)
    LOGGER.info("activated function key group: %s", group_name)
    return True


def activate_next_function_key_group():
    """Advance to the next configured function-key group.

    Returns:
        str | None: The activated group name, or None if no groups exist.
    """
    if not FUNCTION_KEY_GROUPS:
        return None

    group_names = list(FUNCTION_KEY_GROUPS)
    if ACTIVE_FUNCTION_KEY_GROUP not in FUNCTION_KEY_GROUPS:
        next_group = group_names[0]
    else:
        current_index = group_names.index(ACTIVE_FUNCTION_KEY_GROUP)
        next_group = group_names[(current_index + 1) % len(group_names)]

    if switch_active_function_key_group(next_group):
        return next_group
    return None


def get_function_key_selector_entries(group_name=None):
    """Return selector entries (group name, key, description) for a group."""
    entries = []

    if group_name is None:
        group_name = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
        if group_name not in FUNCTION_KEY_GROUPS:
            group_name = ACTIVE_FUNCTION_KEY_GROUP

    if group_name in FUNCTION_KEY_GROUPS:
        for key_name in USER_FUNCTION_KEYS:
            entry = FUNCTION_KEY_GROUPS[group_name].get(key_name)
            if not entry:
                continue
            entries.append(
                {
                    "group_name": group_name,
                    "key": key_name.upper(),
                    "description": entry.get("description") or "",
                }
            )

    return entries


def get_function_key_selector_data():
    """Return selector state for the UI."""
    preview_group = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
    if preview_group not in FUNCTION_KEY_GROUPS:
        preview_group = ACTIVE_FUNCTION_KEY_GROUP

    return {
        "open": FUNCTION_KEY_SELECTOR_STATE.get("open", False),
        "active_group": ACTIVE_FUNCTION_KEY_GROUP,
        "preview_group": preview_group,
    }


_selector_open_filter = Condition(lambda: FUNCTION_KEY_SELECTOR_STATE.get("open", False))


def register_function_key_handlers(key_bindings):
    """Register F1-F8 insertion handlers and selector controls.

    F1-F8 are bound unconditionally so live group switching keeps every user-
    assignable key reachable; the insertion handler is a no-op when the active
    group has no text for the pressed key. F12 always opens/confirms the
    selector. Tab and Escape only fire while the selector is open so normal
    tab-completion and escape-to-abort behavior is preserved otherwise.
    """
    for key_name in USER_FUNCTION_KEYS:
        def handler(event, key_name=key_name):
            insert_function_key_text(event, key_name)

        key_bindings.add(key_name)(handler)

    key_bindings.add("f12")(handle_function_key_selector_key)
    key_bindings.add("tab", filter=_selector_open_filter)(handle_function_key_selector_tab_key)
    # ``eager=True`` short-circuits prompt-toolkit's meta-key wait so a bare
    # ESC fires immediately instead of stalling for the meta-sequence timeout.
    key_bindings.add("escape", filter=_selector_open_filter, eager=True)(handle_function_key_selector_escape_key)

    LOGGER.debug("registered function key handlers (F1-F8 + selector F12/Tab/Escape)")


def insert_function_key_text(event, key_name):
    """Insert configured text for an active-group F-key.

    Args:
        event: The keyboard event.
        key_name: Function key name such as "f1".
    """
    buffer = event.app.current_buffer
    entry = ACTIVE_FUNCTION_KEY_MAPPING.get(key_name, {})
    text = entry.get("text", "")
    if not text:
        return
    LOGGER.info("function key triggered: %s -> %r", key_name, text)
    if buffer.text:
        text = " " + text
    buffer.insert_text(text)


def _update_selector_ui(ui, *, close=False, accept=False):
    if ui is None:
        return
    if hasattr(ui, "items"):
        ui.items = get_function_key_selector_entries(FUNCTION_KEY_SELECTOR_STATE.get("preview_group"))
    if hasattr(ui, "selection"):
        ui.selection = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
    if accept and hasattr(ui, "accept"):
        current_preview = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
        current_item = None
        if current_preview in FUNCTION_KEY_GROUPS:
            entries = get_function_key_selector_entries(current_preview)
            if entries:
                current_item = entries[0]
        if current_item is None:
            current_item = current_preview
        ui.accept(current_item)
    if close and hasattr(ui, "close"):
        ui.close()


def open_function_key_selector(ui=None):
    """Open the function-key selector."""
    if not FUNCTION_KEY_GROUPS:
        LOGGER.info("function key selector not opened: no groups configured")
        return
    FUNCTION_KEY_SELECTOR_STATE["open"] = True
    if FUNCTION_KEY_SELECTOR_STATE.get("preview_group") not in FUNCTION_KEY_GROUPS:
        FUNCTION_KEY_SELECTOR_STATE["preview_group"] = ACTIVE_FUNCTION_KEY_GROUP
    _update_selector_ui(ui)
    _print_function_keys_quick_reference()
    LOGGER.info("function key selector opened")


def close_function_key_selector(cancelled=False, ui=None):
    """Close the function-key selector.

    Args:
        cancelled: Whether the selector was cancelled (Escape) vs confirmed (F12).
        ui: Optional selector UI to close alongside internal state.
    """
    FUNCTION_KEY_SELECTOR_STATE["open"] = False
    FUNCTION_KEY_SELECTOR_STATE["preview_group"] = ACTIVE_FUNCTION_KEY_GROUP
    _update_selector_ui(ui, close=True)
    if cancelled:
        _print_above_prompt(
            f"Selector cancelled (active group: {ACTIVE_FUNCTION_KEY_GROUP})\n"
        )
    else:
        _print_above_prompt(f"Active group: {ACTIVE_FUNCTION_KEY_GROUP}\n")
    LOGGER.info("function key selector closed cancelled=%s", cancelled)


def preview_next_function_key_group(ui=None):
    """Advance the selector preview to the next configured group.

    Returns:
        str | None: The preview group name, or None if no groups exist.
    """
    if not FUNCTION_KEY_GROUPS:
        return None

    group_names = list(FUNCTION_KEY_GROUPS)
    preview_group = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
    if preview_group not in FUNCTION_KEY_GROUPS:
        preview_group = ACTIVE_FUNCTION_KEY_GROUP

    if preview_group not in FUNCTION_KEY_GROUPS:
        preview_group = group_names[0]
    else:
        current_index = group_names.index(preview_group)
        preview_group = group_names[(current_index + 1) % len(group_names)]

    FUNCTION_KEY_SELECTOR_STATE["preview_group"] = preview_group
    _update_selector_ui(ui)
    _print_function_key_selector_output(preview_group)
    LOGGER.info("function key selector preview group=%s", preview_group)
    return preview_group


def handle_function_key_selector_key(event, ui=None):
    """Open the selector when closed, or confirm the preview group when open."""
    if not FUNCTION_KEY_GROUPS:
        return
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        open_function_key_selector(ui=ui)
        return

    preview_group = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
    if preview_group in FUNCTION_KEY_GROUPS:
        switch_active_function_key_group(preview_group)
    _update_selector_ui(ui, accept=True)
    close_function_key_selector(cancelled=False, ui=ui)
    LOGGER.info("function key selector confirmed group=%s", ACTIVE_FUNCTION_KEY_GROUP)


def handle_function_key_selector_confirm_key(event, ui=None):
    """Confirm the selector using the current preview group."""
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        return
    preview_group = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
    if preview_group in FUNCTION_KEY_GROUPS:
        switch_active_function_key_group(preview_group)
    _update_selector_ui(ui, accept=True)
    close_function_key_selector(cancelled=False, ui=ui)
    LOGGER.info("function key selector confirmed group=%s", ACTIVE_FUNCTION_KEY_GROUP)


def handle_function_key_selector_tab_key(event, ui=None):
    """Cycle the selector preview to the next group (spec: Tab when open)."""
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        return
    preview_next_function_key_group(ui=ui)


def handle_function_key_selector_escape_key(event, ui=None):
    """Cancel the selector (spec: Escape when open, no-op otherwise)."""
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        return
    close_function_key_selector(cancelled=True, ui=ui)


# Define the handler for Ctrl + Left Arrow
def ctrl_left_handler(event):
    pass


# Define the handler for Ctrl + Right Arrow
def ctrl_right_handler(event):
    pass


# F10 handler toggles voice record/stop and inserts transcript
def f10_voice_handler(event, config_obj):
    """
    Start or stop voice recording and insert transcript into the prompt.

    Args:
        event: The keyboard event.
        config_obj: Configuration object to set LAST_INPUT_WAS_VOICE flag.
    """
    buffer = event.app.current_buffer
    if not hasattr(f10_voice_handler, "recording"):
        f10_voice_handler.recording = False

    if not f10_voice_handler.recording:
        f10_voice_handler.recording = True
        VOICE_TO_TEXT.start_recording()
    else:
        f10_voice_handler.recording = False
        VOICE_TO_TEXT.stop_recording()
        transcript = VOICE_TO_TEXT.transcribe_async()
        # Insert into buffer at cursor; triggers input-accepted events
        buffer.insert_text(transcript)
        # Set a "voice flag" for next input
        config_obj.LAST_INPUT_WAS_VOICE = True
