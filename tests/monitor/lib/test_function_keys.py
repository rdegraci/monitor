"""Tests for monitor function key configuration and insertion."""

from io import StringIO
from types import SimpleNamespace

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


def test_validate_function_keys_config_normalizes_and_accepts_text_dict():
    """It normalizes mixed-case keys and extracts text from nested config."""
    raw_config = {
        "f1": {"text": "build", "description": "Insert build"},
        "F2": {"text": "git status"},
    }

    result = function_keys.validate_function_keys_config(raw_config)

    assert result == {
        "F1": {"text": "build", "description": "Insert build"},
        "F2": {"text": "git status", "description": ""},
    }


def test_validate_function_keys_config_rejects_invalid_key():
    """It rejects unsupported function key names."""
    with pytest.raises(ValueError):
        function_keys.validate_function_keys_config({"F25": {"text": "noop"}})


def test_load_function_keys_config_reads_json(monkeypatch):
    """It loads and validates function keys from JSON."""
    raw_config = {"F1": {"text": "build", "description": "Insert build"}}
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

    assert result == {"F1": {"text": "build", "description": "Insert build"}}


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


def test_configure_function_key_insertions_normalizes_nested_values():
    """It stores only supported keys and extracts nested text values."""
    keyboard.configure_function_key_insertions(
        {
            "F1": {"text": "build"},
            "F2": "test",
            "F25": "ignored",
        }
    )

    assert keyboard.FUNCTION_KEY_INSERTIONS == {
        "f1": "build",
        "f2": "test",
    }


def test_register_function_key_handlers_registers_configured_keys():
    """It registers only configured function keys using prompt_toolkit names."""
    keyboard.configure_function_key_insertions({"F1": "build", "F3": "git status"})
    bindings = DummyBindings()

    keyboard.register_function_key_handlers(bindings)

    assert [item[0] for item in bindings.registered] == ["f1", "f3"]


def test_insert_function_key_text_appends_space_when_buffer_has_content():
    """It inserts configured text and prefixes a space for non-empty buffers."""
    keyboard.configure_function_key_insertions({"F1": "build"})
    event = DummyEvent("hello")

    keyboard.insert_function_key_text(event, "f1")

    assert event.app.current_buffer.inserted == [" build"]
    assert event.app.current_buffer.text == "hello build"


def test_insert_function_key_text_inserts_without_space_when_buffer_empty():
    """It inserts configured text directly when the buffer is empty."""
    keyboard.configure_function_key_insertions({"F1": "build"})
    event = DummyEvent()

    keyboard.insert_function_key_text(event, "f1")

    assert event.app.current_buffer.inserted == ["build"]
    assert event.app.current_buffer.text == "build"
