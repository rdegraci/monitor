"""Tests for the write-size cap (config.MAX_FILE_WRITE_BYTES + lib.safety).

The cap is the symmetric write-side counterpart to the existing read-side
LARGE_FILE_TOKEN_THRESHOLD. It runs *before* any disk work in each
write-tool entry point: create_file (lib/os.py), text_file_create,
text_file_str_replace_in_file, text_file_insert_text_at_line. Tests
cover the pure helper directly and each of the four wired tools.
"""

import json
import os

import pytest

# Pre-import config to head off the known import-cycle when this file is
# collected before monitor.config has finished initializing.
import monitor.config  # noqa: F401

from monitor import config
from monitor.lib import safety
from monitor.lib import os as monitor_os
from monitor.lib import text_file_editor


# ---------------------------------------------------------------------------
# check_write_size: the pure helper
# ---------------------------------------------------------------------------


def test_check_write_size_allows_under_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 1024, raising=False)
    ok, err = safety.check_write_size("hello world", "test_tool")
    assert ok is True
    assert err is None


def test_check_write_size_allows_at_cap(monkeypatch):
    """Boundary case: cap is inclusive (== passes, > fails). Otherwise
    benchmarking the cap itself becomes ambiguous."""
    payload = "x" * 100
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    ok, err = safety.check_write_size(payload, "test_tool")
    assert ok is True
    assert err is None


def test_check_write_size_rejects_over_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    payload = "x" * 101
    ok, err = safety.check_write_size(payload, "test_tool")
    assert ok is False
    assert "test_tool" in err
    assert "101 bytes" in err
    assert "MAX_FILE_WRITE_BYTES=100" in err


def test_check_write_size_counts_utf8_bytes_not_chars(monkeypatch):
    """A string with multi-byte characters (e.g., emoji) must be measured
    by encoded byte length, not str length — otherwise the cap silently
    leaks ~3-4x its nominal value for non-ASCII content."""
    # Each '🚀' is 4 bytes in UTF-8 but len(s) == 1 char.
    payload = "🚀" * 30  # 120 bytes, 30 chars
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    ok, err = safety.check_write_size(payload, "test_tool")
    assert ok is False
    assert "120 bytes" in err  # the byte count, not the char count


def test_check_write_size_zero_cap_disables(monkeypatch):
    """0 (or unset) is the documented kill-switch — restores pre-cap
    behavior, no rejection regardless of size."""
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 0, raising=False)
    payload = "x" * 10_000_000  # 10 MB
    ok, err = safety.check_write_size(payload, "test_tool")
    assert ok is True
    assert err is None


def test_check_write_size_handles_none_content(monkeypatch):
    """None content (e.g., a tool that omits the payload param) must
    pass through harmlessly — the missing-content case is the tool's
    own problem to validate, not this helper's."""
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    ok, err = safety.check_write_size(None, "test_tool")
    assert ok is True
    assert err is None


def test_check_write_size_reads_config_at_call_time(monkeypatch):
    """The helper must read config.MAX_FILE_WRITE_BYTES dynamically so
    tests and runtime reloads take effect. A module-level snapshot at
    import would defeat both."""
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 1000, raising=False)
    ok, _ = safety.check_write_size("x" * 500, "tool")
    assert ok is True
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    ok, _ = safety.check_write_size("x" * 500, "tool")
    assert ok is False


# ---------------------------------------------------------------------------
# Default value sanity
# ---------------------------------------------------------------------------


def test_default_cap_is_one_mebibyte():
    """Documented default is 1 MiB. If someone changes this, they need
    to also update config.yaml.example and the README — pin the value
    so a silent drift can't happen."""
    assert config.MAX_FILE_WRITE_BYTES == 1_048_576


# ---------------------------------------------------------------------------
# create_file (lib/os.py)
# ---------------------------------------------------------------------------


def test_create_file_rejects_over_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    target = tmp_path / "out.txt"
    result = json.loads(monitor_os.create_file(str(target), "x" * 101))
    assert "error" in result
    assert "create_file" in result["error"]
    # The cap is checked BEFORE disk work — the file must not exist.
    assert not target.exists()


def test_create_file_allows_under_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 1024, raising=False)
    target = tmp_path / "out.txt"
    result = json.loads(monitor_os.create_file(str(target), "small content"))
    assert "result" in result
    assert target.read_text() == "small content"


# ---------------------------------------------------------------------------
# text_file_create (lib/text_file_editor.py)
# ---------------------------------------------------------------------------


def test_text_file_create_rejects_over_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    target = tmp_path / "out.txt"
    result = text_file_editor.text_file_create("create", str(target), "x" * 101)
    assert result["ok"] is False
    assert "text_file_create" in result["error"]
    assert not target.exists()


def test_text_file_create_allows_under_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 1024, raising=False)
    target = tmp_path / "out.txt"
    result = text_file_editor.text_file_create("create", str(target), "small\n")
    assert result["ok"] is True
    assert target.read_text() == "small\n"


# ---------------------------------------------------------------------------
# text_file_str_replace_in_file (lib/text_file_editor.py)
# ---------------------------------------------------------------------------


def test_str_replace_rejects_over_cap_new_str(monkeypatch, tmp_path):
    """The cap applies to ``new_str`` — the payload that gets written.
    ``old_str`` is just a needle; an arbitrarily large old_str that
    never matches is harmless on disk."""
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    target = tmp_path / "out.txt"
    target.write_text("hello world\n")
    result = text_file_editor.text_file_str_replace_in_file(
        "str_replace", str(target), old_str="hello", new_str="x" * 101
    )
    assert result["ok"] is False
    assert "text_file_str_replace_in_file" in result["error"]
    # File contents must be unchanged — cap check runs before write.
    assert target.read_text() == "hello world\n"


def test_str_replace_allows_under_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 1024, raising=False)
    target = tmp_path / "out.txt"
    target.write_text("hello world\n")
    result = text_file_editor.text_file_str_replace_in_file(
        "str_replace", str(target), old_str="hello", new_str="goodbye"
    )
    assert result["ok"] is True
    assert target.read_text() == "goodbye world\n"


# ---------------------------------------------------------------------------
# text_file_insert_text_at_line (lib/text_file_editor.py)
# ---------------------------------------------------------------------------


def test_insert_at_line_rejects_over_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 100, raising=False)
    target = tmp_path / "out.txt"
    target.write_text("existing line\n")
    result = text_file_editor.text_file_insert_text_at_line(
        "insert", str(target), insert_line=1, new_str="x" * 101
    )
    assert result["ok"] is False
    assert "text_file_insert_text_at_line" in result["error"]
    # File untouched.
    assert target.read_text() == "existing line\n"


def test_insert_at_line_allows_under_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_FILE_WRITE_BYTES", 1024, raising=False)
    target = tmp_path / "out.txt"
    target.write_text("existing\n")
    result = text_file_editor.text_file_insert_text_at_line(
        "insert", str(target), insert_line=1, new_str="new line"
    )
    assert result["ok"] is True
    assert "new line" in target.read_text()
