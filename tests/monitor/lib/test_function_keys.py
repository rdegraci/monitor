"""Tests for monitor function key configuration and insertion."""

from io import StringIO

import pytest

from monitor import function_keys
from monitor import function_keys_loader
from monitor.lib import keyboard


class DummyBuffer:
    """Simple buffer that records inserted text."""

    def __init__(self, text=""):
        self.text = text
        self.inserted = []

    def insert_text(self, text):
        self.inserted.append(text)
        self.text += text


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

    def add(self, key_name):
        def decorator(handler):
            self.registered.append((key_name, handler))
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


def test_configure_function_key_insertions_uses_active_group_and_normalizes_values():
    """It stores only the active group's supported keys and extracts nested text values."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                    "F2": {"text": "test", "description": "Insert tests"},
                },
                "group2": {
                    "F3": {"text": "status", "description": "Show status"},
                },
            },
        }
    )

    assert keyboard.FUNCTION_KEY_INSERTIONS == {
        "f1": "build",
        "f2": "test",
    }


def test_get_function_key_selector_entries_exposes_selector_data_from_active_group():
    """It exposes selector entries for the active group without insertion text."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                    "F2": {"text": "test", "description": "Insert tests"},
                },
                "group2": {
                    "F3": {"text": "status", "description": "Show status"},
                },
            },
        }
    )

    selector_entries = keyboard.get_function_key_selector_entries()

    assert selector_entries == [
        {"group_name": "group1", "key": "F1", "description": "Insert build"},
        {"group_name": "group1", "key": "F2", "description": "Insert tests"},
    ]


def test_get_function_key_selector_data_exposes_selector_state_from_active_group():
    """It exposes selector state for the active group."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                    "F2": {"text": "test", "description": "Insert tests"},
                },
                "group2": {
                    "F3": {"text": "status", "description": "Show status"},
                },
            },
        }
    )

    selector_data = keyboard.get_function_key_selector_data()

    assert selector_data == {
        "open": False,
        "active_group": "group1",
        "preview_group": "group1",
    }


def test_register_function_key_handlers_registers_selector_key():
    """It registers the selector entry point instead of raw insertion handlers."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                }
            },
        }
    )
    bindings = DummyBindings()

    keyboard.register_function_key_handlers(bindings)

    assert [item[0] for item in bindings.registered] == ["f1", "f12", "tab", "escape"]


def test_selector_open_uses_current_selection_and_accepts_preview_item():
    """It opens the selector and accepts the selected preview entry."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                    "F2": {"text": "test", "description": "Insert tests"},
                }
            },
        }
    )
    ui = DummyUI([])

    keyboard.open_function_key_selector(ui)

    assert ui.items == [
        {"group_name": "group1", "key": "F1", "description": "Insert build"},
        {"group_name": "group1", "key": "F2", "description": "Insert tests"},
    ]
    assert ui.selected_index == 0
    assert ui.closed is False
    assert ui.accepted == []


def test_selector_tab_moves_to_next_item():
    """It advances the selector selection when tab is pressed."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                    "F2": {"text": "test", "description": "Insert tests"},
                }
            },
        }
    )
    ui = DummyUI(keyboard.get_function_key_selector_entries())

    keyboard.handle_function_key_selector_tab(ui)

    assert ui.items == [
        {"group_name": "group1", "key": "F1", "description": "Insert build"},
        {"group_name": "group1", "key": "F2", "description": "Insert tests"},
    ]
    assert ui.selected_index == 0
    assert ui.closed is False
    assert ui.accepted == []


def test_selector_escape_closes_without_accepting():
    """It closes the selector without accepting when escape is pressed."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                }
            },
        }
    )
    ui = DummyUI(keyboard.get_function_key_selector_entries())

    keyboard.handle_function_key_selector_escape(ui)

    assert keyboard.get_function_key_selector_data() == {
        "open": False,
        "active_group": "group1",
        "preview_group": "group1",
    }


def test_selector_confirm_accepts_current_preview_item():
    """It accepts the current preview entry when confirm is pressed."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                    "F2": {"text": "test", "description": "Insert tests"},
                }
            },
        }
    )
    ui = DummyUI(keyboard.get_function_key_selector_entries())

    keyboard.handle_function_key_selector_confirm_key(ui)

    assert keyboard.get_function_key_selector_data() == {
        "open": False,
        "active_group": "group1",
        "preview_group": "group1",
    }


def test_insert_function_key_text_uses_active_group_insertion():
    """It inserts configured text for the active group."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                }
            },
        }
    )
    event = DummyEvent("hello")

    keyboard.insert_function_key_text(event, "f1")

    assert event.app.current_buffer.inserted == [" build"]
    assert event.app.current_buffer.text == "hello build"


def test_insert_function_key_text_inserts_without_space_when_buffer_empty():
    """It inserts configured text directly when the buffer is empty."""
    keyboard.configure_function_key_insertions(
        {
            "active_group": "group1",
            "groups": {
                "group1": {
                    "F1": {"text": "build", "description": "Insert build"},
                }
            },
        }
    )
    event = DummyEvent()

    keyboard.insert_function_key_text(event, "f1")

    assert event.app.current_buffer.inserted == ["build"]
    assert event.app.current_buffer.text == "build"
