import logging

from monitor.lib.voice_to_text import VoiceToText

LOGGER = logging.getLogger(__name__)

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


def _normalize_function_key_mapping(group_name, group_mapping):
    """Normalize a grouped function-key mapping to F1-F24 text entries."""
    normalized_mapping = {}

    if not isinstance(group_mapping, dict):
        LOGGER.info("skipping function key group %s: expected mapping", group_name)
        return normalized_mapping

    for key, value in group_mapping.items():
        if not isinstance(key, str):
            continue

        normalized_key = key.lower()
        if not normalized_key.startswith("f"):
            continue
        if not normalized_key[1:].isdigit():
            continue

        key_number = int(normalized_key[1:])
        if not 1 <= key_number <= 24:
            continue
        if normalized_key in normalized_mapping:
            LOGGER.info(
                "duplicate function key ignored in group %s: %s",
                group_name,
                normalized_key,
            )
            continue

        description = None
        text = None
        if isinstance(value, dict):
            description = value.get("description")
            text = value.get("text")
        elif isinstance(value, str):
            text = value

        if isinstance(text, str):
            normalized_mapping[normalized_key] = {"text": text, "description": description}

    return normalized_mapping


def _normalize_function_key_configuration(function_key_insertions):
    """Normalize supported grouped function-key configuration shapes."""
    active_group = None
    groups = {}

    if not isinstance(function_key_insertions, dict):
        return active_group, groups

    if "groups" in function_key_insertions and isinstance(function_key_insertions.get("groups"), dict):
        active_group = function_key_insertions.get("active_group")
        raw_groups = function_key_insertions.get("groups", {})
        if isinstance(active_group, str):
            active_group = active_group.strip() or None
        else:
            active_group = None
    else:
        raw_groups = function_key_insertions

    for group_name, group_mapping in raw_groups.items():
        if not isinstance(group_name, str):
            LOGGER.info("skipping function key group with non-string name: %r", group_name)
            continue

        normalized_group_name = group_name.strip()
        if not normalized_group_name:
            continue

        normalized_mapping = _normalize_function_key_mapping(normalized_group_name, group_mapping)
        if normalized_mapping:
            groups[normalized_group_name] = normalized_mapping

    if active_group not in groups:
        active_group = next(iter(groups), None)

    return active_group, groups


def _format_function_key_selector_output(group_name):
    """Format the current function-key selector group and entries for display."""
    if group_name not in FUNCTION_KEY_GROUPS:
        return "Function key selector: no active group\n"

    lines = [f"Function key selector: {group_name}"]
    for entry in get_function_key_selector_entries(group_name):
        lines.append(f"{entry['key']}: {entry['description']}")
    return "\n".join(lines) + "\n"


def _print_function_key_selector_output(group_name):
    """Print the current function-key selector contents for the user."""
    rendered_output = _format_function_key_selector_output(group_name)
    print(rendered_output)
    LOGGER.info("function key selector displayed for group=%s", group_name)


def _reset_function_key_selector_state():
    """Reset selector runtime state to the normal prompt state."""
    global FUNCTION_KEY_SELECTOR_STATE
    FUNCTION_KEY_SELECTOR_STATE = {
        "open": False,
        "preview_group": None,
    }


def _set_active_function_key_group(group_name):
    """Set the active function-key group and runtime insertion mapping."""
    global ACTIVE_FUNCTION_KEY_GROUP
    global ACTIVE_FUNCTION_KEY_MAPPING
    global FUNCTION_KEY_INSERTIONS
    global FUNCTION_KEY_SELECTOR_STATE

    if group_name not in FUNCTION_KEY_GROUPS:
        ACTIVE_FUNCTION_KEY_GROUP = None
        ACTIVE_FUNCTION_KEY_MAPPING = {}
        FUNCTION_KEY_INSERTIONS = {}
        FUNCTION_KEY_SELECTOR_STATE["preview_group"] = None
        return False

    ACTIVE_FUNCTION_KEY_GROUP = group_name
    ACTIVE_FUNCTION_KEY_MAPPING = FUNCTION_KEY_GROUPS[group_name]
    FUNCTION_KEY_INSERTIONS = {
        key_name: entry.get("text", "")
        for key_name, entry in ACTIVE_FUNCTION_KEY_MAPPING.items()
        if key_name in {f"f{i}" for i in range(1, 9)}
    }
    FUNCTION_KEY_SELECTOR_STATE["preview_group"] = group_name
    return True


def configure_function_key_insertions(function_key_insertions):
    """Store validated grouped function-key text insertions.

    Args:
        function_key_insertions: Normalized mapping of group names to key
            mappings. Each key mapping contains validated function-key names
            mapped to string values or dictionaries with text/description.
    """
    global FUNCTION_KEY_GROUPS
    global FUNCTION_KEY_INSERTIONS
    global ACTIVE_FUNCTION_KEY_GROUP
    global ACTIVE_FUNCTION_KEY_MAPPING
    global FUNCTION_KEY_SELECTOR_STATE

    FUNCTION_KEY_GROUPS = {}
    FUNCTION_KEY_INSERTIONS = {}

    active_group, normalized_groups = _normalize_function_key_configuration(function_key_insertions)
    FUNCTION_KEY_GROUPS = normalized_groups

    if not FUNCTION_KEY_GROUPS:
        ACTIVE_FUNCTION_KEY_GROUP = None
        ACTIVE_FUNCTION_KEY_MAPPING = {}
        FUNCTION_KEY_SELECTOR_STATE = {"open": False, "preview_group": None}
        LOGGER.info("no valid function key groups configured")
        return

    if active_group not in FUNCTION_KEY_GROUPS:
        active_group = next(iter(FUNCTION_KEY_GROUPS))

    _set_active_function_key_group(active_group)
    FUNCTION_KEY_SELECTOR_STATE = {
        "open": False,
        "preview_group": ACTIVE_FUNCTION_KEY_GROUP,
    }
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
    """Return selector entries for a group."""
    entries = []

    if group_name is None:
        group_name = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
        if group_name not in FUNCTION_KEY_GROUPS:
            group_name = ACTIVE_FUNCTION_KEY_GROUP

    if group_name in FUNCTION_KEY_GROUPS:
        for key_name in (f"f{i}" for i in range(1, 25)):
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


def register_function_key_handlers(key_bindings):
    """Register active-group F1-F8 insertions and selector controls."""
    bound_keys = 0
    for key_name in (f"f{i}" for i in range(1, 9)):
        if key_name not in FUNCTION_KEY_INSERTIONS:
            continue

        def handler(event, key_name=key_name):
            insert_function_key_text(event, key_name)

        key_bindings.add(key_name)(handler)
        bound_keys += 1

    def _bind_selector(key_name, handler):
        key_bindings.add(key_name)(handler)

    _bind_selector("f12", handle_function_key_selector_key)
    _bind_selector("tab", handle_function_key_selector_tab_key)
    _bind_selector("escape", handle_function_key_selector_escape_key)

    LOGGER.debug("registered %d function key handler(s)", bound_keys)


def insert_function_key_text(event, key_name):
    """Insert configured text for a validated function key.

    Args:
        event: The keyboard event.
        key_name: Validated function key name such as "f1" or "f10".
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
    FUNCTION_KEY_SELECTOR_STATE["open"] = True
    if FUNCTION_KEY_SELECTOR_STATE.get("preview_group") not in FUNCTION_KEY_GROUPS:
        FUNCTION_KEY_SELECTOR_STATE["preview_group"] = ACTIVE_FUNCTION_KEY_GROUP
    _update_selector_ui(ui)
    _print_function_key_selector_output(FUNCTION_KEY_SELECTOR_STATE.get("preview_group"))
    LOGGER.info("function key selector opened")


def close_function_key_selector(cancelled=False, ui=None):
    """Close the function-key selector.

    Args:
        cancelled: Whether the selector was cancelled.
    """
    FUNCTION_KEY_SELECTOR_STATE["open"] = False
    FUNCTION_KEY_SELECTOR_STATE["preview_group"] = ACTIVE_FUNCTION_KEY_GROUP
    _update_selector_ui(ui, close=True)
    _reset_function_key_selector_state()
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
    """Open or confirm the selector."""
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        open_function_key_selector(ui=ui)
        return

    preview_group = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
    if preview_group in FUNCTION_KEY_GROUPS:
        switch_active_function_key_group(preview_group)
    close_function_key_selector(cancelled=False, ui=ui)
    _update_selector_ui(ui, accept=True)
    LOGGER.info("function key selector confirmed group=%s", ACTIVE_FUNCTION_KEY_GROUP)


def handle_function_key_selector_confirm_key(event, ui=None):
    """Confirm the selector using the current preview group."""
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        if ui is not None:
            _update_selector_ui(ui, accept=True)
        return

    preview_group = FUNCTION_KEY_SELECTOR_STATE.get("preview_group")
    if preview_group in FUNCTION_KEY_GROUPS:
        switch_active_function_key_group(preview_group)
    _update_selector_ui(ui, accept=True)
    close_function_key_selector(cancelled=False, ui=ui)
    LOGGER.info("function key selector confirmed group=%s", ACTIVE_FUNCTION_KEY_GROUP)


def handle_function_key_selector_tab_key(event, ui=None):
    """Cycle the selector preview to the next group."""
    if ui is not None:
        preview_next_function_key_group(ui=ui)
        if not FUNCTION_KEY_SELECTOR_STATE.get("open", False) and hasattr(ui, "select_next"):
            ui.select_next()
        return
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        return
    preview_next_function_key_group(ui=ui)


def handle_function_key_selector_tab(event, ui=None):
    """Compatibility wrapper for selector tab handling."""
    handle_function_key_selector_tab_key(event, ui=ui)


def handle_function_key_selector_escape_key(event, ui=None):
    """Cancel the selector."""
    if not FUNCTION_KEY_SELECTOR_STATE.get("open", False):
        return
    close_function_key_selector(cancelled=True, ui=ui)
    if ui is not None and hasattr(ui, "close"):
        ui.close()


def handle_function_key_selector_escape(event, ui=None):
    """Compatibility wrapper for selector escape handling."""
    handle_function_key_selector_escape_key(event, ui=ui)


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
