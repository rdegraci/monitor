"""Tests for monitor function key configuration and insertion."""

from io import StringIO

import pytest

from monitor import function_keys
from monitor import function_keys_loader
from monitor.lib import keyboard


class DummyBuffer:
    """Buffer stand-in with a cursor that records inserted text.

    Mirrors enough of prompt_toolkit.buffer.Buffer for the keyboard handlers:
    cursor-aware insert_text and delete_before_cursor. ``inserted`` keeps the
    history of insert_text calls for assertions.
    """

    def __init__(self, text=""):
        self.text = text
        self.cursor_position = len(text)
        self.inserted = []

    def insert_text(self, text):
        self.inserted.append(text)
        pos = self.cursor_position
        self.text = self.text[:pos] + text + self.text[pos:]
        self.cursor_position = pos + len(text)

    def delete_before_cursor(self, count):
        pos = self.cursor_position
        start = max(0, pos - count)
        deleted = self.text[start:pos]
        self.text = self.text[:start] + self.text[pos:]
        self.cursor_position = start
        return deleted


class DummyApp:
    """Simple app wrapper exposing a current buffer."""

    def __init__(self, text=""):
        self.current_buffer = DummyBuffer(text)


class DummyEvent:
    """Simple event object compatible with keyboard handlers."""

    def __init__(self, text=""):
        self.app = DummyApp(text)


class DummyBindings:
    """Minimal key binding collector used for registration tests."""

    def __init__(self):
        self.registered = []

    def add(self, key_name, **kwargs):
        def decorator(handler):
            self.registered.append((key_name, handler, kwargs))
            return handler

        return decorator


class DummyUI:
    def __init__(self, items):
        self.items = list(items)
        self.selected_index = 0
        self.closed = False
        self.accepted = []

    def set_items(self, items):
        self.items = list(items)

    def select_next(self):
        self.selected_index += 1

    def select_previous(self):
        self.selected_index -= 1

    def close(self):
        self.closed = True

    def accept(self, item):
        self.accepted.append(item)


def _two_group_config():
    """Spec-shape grouped config used by selector tests."""
    return {
        "group1": {
            "F1": {"text": "build", "description": "Insert build"},
            "F2": {"text": "test", "description": "Insert tests"},
        },
        "group2": {
            "F3": {"text": "status", "description": "Show status"},
        },
    }


def _cycle_config():
    """Single group with three consecutive F-keys, for cycle tests."""
    return {
        "g": {
            "F1": {"text": "one", "description": "d1"},
            "F2": {"text": "two", "description": "d2"},
            "F3": {"text": "three", "description": "d3"},
        }
    }


@pytest.fixture(autouse=True)
def captured_prints(monkeypatch):
    """Capture every line our keyboard module routes through _print_above_prompt.

    In production this goes through prompt-toolkit's run_in_terminal — we don't
    want to invoke that during tests (it requires a live application), so we
    replace the helper with a list sink for every test in this module.
    """
    sink = []
    monkeypatch.setattr(keyboard, "_print_above_prompt", lambda text: sink.append(text))
    return sink


def test_validate_function_keys_config_accepts_grouped_json_shape():
    """It accepts grouped configurations with text and description entries."""
    raw_config = {
        "group1": {
            "F1": {"text": "build", "description": "Insert build"},
            "F2": {"text": "test", "description": "Insert tests"},
        },
        "group2": {
            "F3": {"text": "status", "description": "Show status"},
        },
    }

    result = function_keys.validate_function_keys_config(raw_config)

    assert result == {
        "group1": {
            "F1": {"text": "build", "description": "Insert build"},
            "F2": {"text": "test", "description": "Insert tests"},
        },
        "group2": {
            "F3": {"text": "status", "description": "Show status"},
        },
    }


def test_validate_function_keys_config_requires_text_and_description_fields():
    """It rejects entries missing either required field."""
    with pytest.raises(ValueError):
        function_keys.validate_function_keys_config(
            {"group1": {"F1": {"text": "build"}}}
        )

    with pytest.raises(ValueError):
        function_keys.validate_function_keys_config(
            {"group1": {"F1": {"description": "Insert build"}}}
        )


def test_validate_function_keys_config_allows_duplicate_function_keys_across_groups():
    """It preserves each group independently when the same key appears in multiple groups."""
    raw_config = {
        "group1": {"F1": {"text": "build", "description": "Insert build"}},
        "group2": {"F1": {"text": "test", "description": "Insert tests"}},
    }

    result = function_keys.validate_function_keys_config(raw_config)

    assert result == {
        "group1": {"F1": {"text": "build", "description": "Insert build"}},
        "group2": {"F1": {"text": "test", "description": "Insert tests"}},
    }


def test_validate_function_keys_config_rejects_f9_through_f12():
    """It rejects reserved function keys in the F9-F12 range."""
    for key_name in ("F9", "F10", "F11", "F12"):
        with pytest.raises(ValueError):
            function_keys.validate_function_keys_config(
                {"group1": {key_name: {"text": "noop", "description": "noop"}}}
            )


def test_load_function_keys_config_reads_grouped_json(monkeypatch):
    """It loads and validates grouped function keys from JSON."""
    raw_config = {
        "group1": {
            "F1": {"text": "build", "description": "Insert build"},
            "F2": {"text": "test", "description": "Insert tests"},
        }
    }
    monkeypatch.setattr(
        function_keys_loader,
        "find_config_file",
        lambda filename: "/tmp/function_keys.json",
    )
    monkeypatch.setattr(
        function_keys_loader,
        "open",
        lambda *args, **kwargs: StringIO(str(raw_config).replace("'", '"')),
        raising=False,
    )

    result = function_keys_loader.load_function_keys_config()

    assert result == raw_config


def test_load_function_keys_config_rejects_malformed_json(monkeypatch):
    """It raises when the JSON cannot be parsed."""
    monkeypatch.setattr(
        function_keys_loader,
        "find_config_file",
        lambda filename: "/tmp/function_keys.json",
    )
    monkeypatch.setattr(
        function_keys_loader,
        "open",
        lambda *args, **kwargs: StringIO("not-json"),
        raising=False,
    )

    with pytest.raises(RuntimeError):
        function_keys_loader.load_function_keys_config()


def test_configure_function_key_insertions_activates_first_group():
    """It activates the first configured group at startup (spec: session-local default)."""
    keyboard.configure_function_key_insertions(_two_group_config())

    assert keyboard.ACTIVE_FUNCTION_KEY_GROUP == "group1"
    assert keyboard.FUNCTION_KEY_INSERTIONS == {
        "f1": "build",
        "f2": "test",
    }


def test_configure_function_key_insertions_resets_to_first_group_on_reload():
    """It resets the active group to the first on every reload (spec: non-persistence)."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.switch_active_function_key_group("group2")
    assert keyboard.ACTIVE_FUNCTION_KEY_GROUP == "group2"

    keyboard.configure_function_key_insertions(_two_group_config())

    assert keyboard.ACTIVE_FUNCTION_KEY_GROUP == "group1"


def test_get_function_key_selector_entries_exposes_selector_data_from_active_group():
    """It exposes selector entries for the active group without insertion text."""
    keyboard.configure_function_key_insertions(_two_group_config())

    selector_entries = keyboard.get_function_key_selector_entries()

    assert selector_entries == [
        {"group_name": "group1", "key": "F1", "description": "Insert build"},
        {"group_name": "group1", "key": "F2", "description": "Insert tests"},
    ]


def test_get_function_key_selector_data_exposes_selector_state_from_active_group():
    """It exposes selector state for the active group."""
    keyboard.configure_function_key_insertions(_two_group_config())

    selector_data = keyboard.get_function_key_selector_data()

    assert selector_data == {
        "open": False,
        "active_group": "group1",
        "preview_group": "group1",
    }


def test_register_function_key_handlers_binds_all_f1_through_f8_unconditionally():
    """It binds every F1-F8 so live group switching keeps each key reachable."""
    keyboard.configure_function_key_insertions(
        {"group1": {"F1": {"text": "build", "description": "Insert build"}}}
    )
    bindings = DummyBindings()

    keyboard.register_function_key_handlers(bindings)

    bound_user_keys = [item[0] for item in bindings.registered if item[0].startswith("f") and item[0] != "f12"]
    assert bound_user_keys == ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8"]


def test_register_function_key_handlers_gates_tab_and_escape_to_selector_open():
    """It attaches a selector-open filter to Tab and Escape so normal keys still work."""
    keyboard.configure_function_key_insertions(
        {"group1": {"F1": {"text": "build", "description": "Insert build"}}}
    )
    bindings = DummyBindings()

    keyboard.register_function_key_handlers(bindings)

    by_key = {item[0]: item[2] for item in bindings.registered}
    assert "filter" in by_key["tab"]
    assert "filter" in by_key["escape"]
    assert by_key.get("f12", {}).get("filter") is None


def test_register_function_key_handlers_marks_escape_eager():
    """Escape uses eager=True so it fires immediately past prompt-toolkit's meta-key wait."""
    keyboard.configure_function_key_insertions(
        {"group1": {"F1": {"text": "build", "description": "Insert build"}}}
    )
    bindings = DummyBindings()

    keyboard.register_function_key_handlers(bindings)

    by_key = {item[0]: item[2] for item in bindings.registered}
    assert by_key["escape"].get("eager") is True
    assert by_key["tab"].get("eager") is None


def test_register_function_key_handlers_binds_keys_any_with_selector_filter():
    """The catch-all 'any key cancels' binding is registered with the selector filter."""
    from prompt_toolkit.keys import Keys

    keyboard.configure_function_key_insertions(
        {"group1": {"F1": {"text": "build", "description": "Insert build"}}}
    )
    bindings = DummyBindings()

    keyboard.register_function_key_handlers(bindings)

    any_entries = [item for item in bindings.registered if item[0] is Keys.Any]
    assert len(any_entries) == 1
    assert "filter" in any_entries[0][2]


def test_selector_open_uses_current_selection_and_accepts_preview_item():
    """It opens the selector and pushes preview entries to the UI."""
    keyboard.configure_function_key_insertions(
        {
            "group1": {
                "F1": {"text": "build", "description": "Insert build"},
                "F2": {"text": "test", "description": "Insert tests"},
            }
        }
    )
    ui = DummyUI([])

    keyboard.open_function_key_selector(ui=ui)

    assert ui.items == [
        {"group_name": "group1", "key": "F1", "description": "Insert build"},
        {"group_name": "group1", "key": "F2", "description": "Insert tests"},
    ]
    assert ui.closed is False
    assert ui.accepted == []


def test_selector_tab_does_nothing_when_selector_is_closed():
    """It is a no-op when the selector is not open (preserves normal tab behavior)."""
    keyboard.configure_function_key_insertions(_two_group_config())
    ui = DummyUI(keyboard.get_function_key_selector_entries())

    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=ui)

    assert keyboard.get_function_key_selector_data()["preview_group"] == "group1"


def test_selector_tab_advances_preview_when_open():
    """It advances to the next group when the selector is open."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.open_function_key_selector(ui=None)

    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=None)

    assert keyboard.get_function_key_selector_data()["preview_group"] == "group2"


def test_selector_tab_wraps_back_to_first_group():
    """It wraps preview selection back to the first group."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.open_function_key_selector(ui=None)

    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=None)
    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=None)

    assert keyboard.get_function_key_selector_data()["preview_group"] == "group1"


def test_selector_escape_closes_without_changing_active_group():
    """It closes the selector and leaves the active group unchanged."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.open_function_key_selector(ui=None)
    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=None)

    keyboard.handle_function_key_selector_escape_key(DummyEvent(), ui=None)

    data = keyboard.get_function_key_selector_data()
    assert data["open"] is False
    assert data["active_group"] == "group1"
    assert data["preview_group"] == "group1"


def test_selector_escape_prints_visible_cancel_feedback(captured_prints):
    """Escape prints a visible 'cancelled' line so the user sees the close take effect."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)
    captured_prints.clear()

    keyboard.handle_function_key_selector_escape_key(DummyEvent(), ui=None)

    assert len(captured_prints) == 1
    assert "Selector cancelled" in captured_prints[0]
    assert "group1" in captured_prints[0]


def test_selector_confirm_prints_visible_active_group_feedback(captured_prints):
    """F12 confirm prints the new active group in yellow with a leading newline."""
    from monitor.lib.colors import reset, yellow

    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)
    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=None)
    captured_prints.clear()

    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)

    matching = [line for line in captured_prints if "Active group: group2" in line]
    assert matching, "expected an 'Active group: group2' line"
    line = matching[0]
    assert line.startswith("\n"), "confirm output should start with a newline"
    assert yellow in line
    assert reset in line


def test_selector_confirm_activates_previewed_group():
    """F12 while open switches the active group to the previewed one."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.open_function_key_selector(ui=None)
    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=None)

    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)

    data = keyboard.get_function_key_selector_data()
    assert data["open"] is False
    assert data["active_group"] == "group2"
    assert keyboard.FUNCTION_KEY_INSERTIONS == {"f3": "status"}


def test_selector_does_not_open_when_no_groups_configured():
    """F12 with no groups configured is a no-op (no empty selector)."""
    keyboard.configure_function_key_insertions({})

    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)

    assert keyboard.get_function_key_selector_data()["open"] is False


def test_insert_function_key_text_uses_active_group_insertion():
    """It inserts configured text for the active group."""
    keyboard.configure_function_key_insertions(
        {"group1": {"F1": {"text": "build", "description": "Insert build"}}}
    )
    event = DummyEvent("hello")

    keyboard.insert_function_key_text(event, "f1")

    assert event.app.current_buffer.inserted == [" build"]
    assert event.app.current_buffer.text == "hello build"


def test_insert_function_key_text_inserts_without_space_when_buffer_empty():
    """It inserts configured text directly when the buffer is empty."""
    keyboard.configure_function_key_insertions(
        {"group1": {"F1": {"text": "build", "description": "Insert build"}}}
    )
    event = DummyEvent()

    keyboard.insert_function_key_text(event, "f1")

    assert event.app.current_buffer.inserted == ["build"]
    assert event.app.current_buffer.text == "build"


def test_insert_function_key_text_after_group_switch_uses_new_group_text():
    """Switching groups makes the new group's text active for all F1-F8 keys."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.switch_active_function_key_group("group2")
    event = DummyEvent()

    keyboard.insert_function_key_text(event, "f3")

    assert event.app.current_buffer.inserted == ["status"]


def test_insert_function_key_text_is_noop_when_active_group_has_no_binding():
    """A bound F-key with no entry in the active group inserts nothing."""
    keyboard.configure_function_key_insertions(_two_group_config())
    event = DummyEvent()

    keyboard.insert_function_key_text(event, "f3")  # F3 is in group2, not active group1

    assert event.app.current_buffer.inserted == []


class _AnyKeyEvent:
    """Event stand-in for prompt_toolkit's Keys.Any handler: carries .data."""

    def __init__(self, data, text=""):
        self.data = data
        self.app = DummyApp(text)


def test_typing_a_letter_while_selector_open_cancels_and_inserts(captured_prints):
    """While the selector is open, a regular keystroke cancels it and inserts the char."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)
    captured_prints.clear()

    event = _AnyKeyEvent("h")
    keyboard.handle_function_key_selector_any_key(event, ui=None)

    assert keyboard.get_function_key_selector_data()["open"] is False
    assert event.app.current_buffer.inserted == ["h"]
    assert captured_prints == []  # silent cancel — the inserted char is the feedback


def test_typing_special_key_while_selector_open_cancels_without_inserting(captured_prints):
    """Non-printable event.data (e.g., empty for arrow keys) cancels silently, no insert."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)
    captured_prints.clear()

    event = _AnyKeyEvent("")
    keyboard.handle_function_key_selector_any_key(event, ui=None)

    assert keyboard.get_function_key_selector_data()["open"] is False
    assert event.app.current_buffer.inserted == []


def test_pressing_f1_while_selector_open_cancels_and_inserts_text(captured_prints):
    """F1-F8 close the selector silently and proceed with their normal insertion."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)
    captured_prints.clear()

    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")

    assert keyboard.get_function_key_selector_data()["open"] is False
    assert event.app.current_buffer.inserted == ["build"]
    assert captured_prints == []  # silent — the inserted text is the feedback


def test_tab_cycle_after_f_key_advances_through_keys():
    """After an F-key insertion, Tab replaces the text with the next key's text."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")
    assert event.app.current_buffer.text == "one"

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "two"

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "three"


def test_tab_cycle_wraps_last_key_back_to_first():
    """Cycling past the last configured key wraps around to the first."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f3")
    assert event.app.current_buffer.text == "three"

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "one"


def test_tab_cycle_skips_unconfigured_keys():
    """Cycling only visits configured F-keys (sparse groups skip the gaps)."""
    keyboard.configure_function_key_insertions(
        {
            "g": {
                "F1": {"text": "one", "description": "d"},
                "F3": {"text": "three", "description": "d"},
            }
        }
    )
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")
    assert event.app.current_buffer.text == "one"

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "three"

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "one"


def test_tab_cycle_is_noop_when_cursor_moved():
    """If the user types after the F-key, the cursor diverges and Tab does not cycle."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")
    event.app.current_buffer.insert_text("X")  # user typed; cursor past anchor
    assert event.app.current_buffer.text == "oneX"

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)

    assert event.app.current_buffer.text == "oneX"  # unchanged
    # State was cleared; a second Tab also does nothing.
    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "oneX"


def test_tab_cycle_preserves_leading_space_with_nonempty_buffer():
    """Cycling re-applies the leading-space rule against the preceding text."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent("hello")
    keyboard.insert_function_key_text(event, "f1")
    assert event.app.current_buffer.text == "hello one"

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "hello two"


def test_tab_cycle_resets_on_group_switch():
    """Switching the active group disarms the cycle (old key is meaningless)."""
    keyboard.configure_function_key_insertions(_two_group_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")
    assert event.app.current_buffer.text == "build"

    keyboard.switch_active_function_key_group("group2")

    keyboard.handle_function_key_cycle_tab_key(event, ui=None)
    assert event.app.current_buffer.text == "build"  # unchanged: cycle was reset


def test_get_preview_range_active_only_while_cursor_at_end():
    """get_preview_range returns the range at the anchor, None once the cursor moves."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")  # inserts "one" at [0, 3]

    assert keyboard.get_preview_range(3) == (0, 3)
    assert keyboard.get_preview_range(2) is None  # cursor moved off the end
    assert keyboard.get_preview_range(4) is None


def test_get_preview_range_none_after_reset():
    """No preview is reported once disarmed."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")
    keyboard._reset_function_key_preview()

    assert keyboard.get_preview_range(3) is None


def test_escape_discards_pending_preview():
    """ESC while a preview is pending deletes the gray text and disarms."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent("hello ")
    keyboard.insert_function_key_text(event, "f1")
    # buffer non-empty -> leading space added: "hello  one"? no: "hello " + " one"
    assert event.app.current_buffer.text == "hello  one"

    keyboard.handle_function_key_preview_escape_key(event, ui=None)

    assert event.app.current_buffer.text == "hello "  # preview removed
    assert keyboard.get_preview_range(event.app.current_buffer.cursor_position) is None


def test_escape_discard_is_noop_without_preview():
    """ESC discard does nothing when no preview is pending."""
    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent("typed text")

    keyboard.handle_function_key_preview_escape_key(event, ui=None)

    assert event.app.current_buffer.text == "typed text"


def test_lexer_grays_pending_preview_range():
    """The lexer paints the pending preview range with the fkey-preview style."""
    from prompt_toolkit.document import Document

    from monitor.lib.lexer import RedAfter120Lexer

    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")  # preview "one" at [0, 3]

    document = Document("one", cursor_position=3)
    get_line = RedAfter120Lexer().lex_document(document)

    assert get_line(0) == [("class:fkey-preview", "one")]


def test_lexer_does_not_gray_once_cursor_moves():
    """Once the cursor leaves the preview end, the text renders normally (accepted)."""
    from prompt_toolkit.document import Document

    from monitor.lib.lexer import RedAfter120Lexer

    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")  # preview "one" at [0, 3]

    # User typed an "x": cursor now at 4, past the preview end.
    document = Document("onex", cursor_position=4)
    get_line = RedAfter120Lexer().lex_document(document)

    assert get_line(0) == [("", "onex")]


def test_lexer_grays_preview_and_keeps_red_after_120():
    """Preview gray and red-past-120 compose on the same line."""
    from prompt_toolkit.document import Document

    from monitor.lib.lexer import RedAfter120Lexer

    keyboard.configure_function_key_insertions(_cycle_config())
    event = DummyEvent()
    keyboard.insert_function_key_text(event, "f1")  # preview at [0, 3]

    long_line = "one" + ("a" * 130)  # 133 chars; preview is the first 3
    document = Document(long_line, cursor_position=3)
    get_line = RedAfter120Lexer().lex_document(document)
    fragments = get_line(0)

    assert fragments[0] == ("class:fkey-preview", "one")
    # remainder splits at column 120 into normal then red
    assert fragments[1][0] == ""
    assert fragments[-1][0] == "class:red"
    assert "".join(text for _, text in fragments) == long_line


def test_selector_open_renders_full_reference_and_hint(captured_prints):
    """It writes the multi-group reference plus hint above the prompt safely."""
    keyboard.configure_function_key_insertions(_two_group_config())

    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)

    assert len(captured_prints) == 1
    rendered = captured_prints[0]
    assert "[group1] (active)" in rendered
    assert "[group2]" in rendered
    assert "F1: Insert build" in rendered
    assert "F2: Insert tests" in rendered
    assert "F3: Show status" in rendered
    assert "TAB to cycle groups. F12 to choose. ESC to cancel. Any key to dismiss." in rendered
    assert "After an F-key insert, TAB cycles F1-F8." in rendered


def test_selector_tab_renders_preview_group(captured_prints):
    """It writes preview output above the prompt on each Tab, with a leading newline."""
    keyboard.configure_function_key_insertions(_two_group_config())
    keyboard.handle_function_key_selector_key(DummyEvent(), ui=None)
    captured_prints.clear()

    keyboard.handle_function_key_selector_tab_key(DummyEvent(), ui=None)

    assert len(captured_prints) == 1
    rendered = captured_prints[0]
    assert rendered.startswith("\n"), "preview output should start with a newline"
    assert "Function key selector: group2" in rendered
