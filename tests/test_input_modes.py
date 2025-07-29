
import pytest
from unittest.mock import patch
from monitor.lib import input_modes

def test_handle_single_line_returns_line():
    assert input_modes.handle_single_line("hi there") == ["hi there"]

def test_handle_multi_command_reads_until_eof():
    inputs = iter(["foo", "bar", "EOF"])
    with patch("builtins.input", lambda _: next(inputs)):
        result = input_modes.handle_multi_command("first")
    assert result == ["foo;;;", "bar;;;"]

def test_handle_multi_command_eoferror(monkeypatch, capsys):
    calls = iter(["foo"])
    def fake_input(prompt):
        v = next(calls)
        raise EOFError if v == "foo" else ""
    monkeypatch.setattr("builtins.input", fake_input)
    result = input_modes.handle_multi_command("first")
    assert result == []
    out, _ = capsys.readouterr()
    assert "EOF" in out

def test_handle_backslash_continuation_reads_until_eof():
    inputs = iter(["line1", "EOF"])
    with patch("builtins.input", lambda _: next(inputs)):
        lines = input_modes.handle_backslash_continuation("hello \\")
    assert lines == ["!<hello ", "!<line1"]

def test_handle_backslash_continuation_eoferror(monkeypatch, capsys):
    calls = iter(["foo"])
    def fake_input(prompt):
        v = next(calls)
        raise EOFError if v == "foo" else ""
    monkeypatch.setattr("builtins.input", fake_input)
    lines = input_modes.handle_backslash_continuation("hi \\")
    assert lines == ["!<hi "]
    out, _ = capsys.readouterr()
    assert "EOF" in out

def test_handle_pipeline_command_until_eof():
    inputs = iter(["cmd2", "cmd3", "EOF"])
    with patch("builtins.input", lambda _: next(inputs)):
        result = input_modes.handle_pipeline_command("|cmd1")
    assert result == ["cmd1", "cmd2", "cmd3"]

def test_handle_pipeline_command_empty(monkeypatch, capsys):
    inputs = iter([""])
    def fake_input(prompt):
        return next(inputs)
    monkeypatch.setattr("builtins.input", fake_input)
    result = input_modes.handle_pipeline_command("|cmd1")
    assert result == ["cmd1"]
    out, _ = capsys.readouterr()
    assert "EOF" not in out and "ended by user" not in out

def test_handle_pipeline_command_eof(monkeypatch, capsys):
    inputs = iter(["EOF"])
    def fake_input(prompt):
        return next(inputs)
    monkeypatch.setattr("builtins.input", fake_input)
    result = input_modes.handle_pipeline_command("|cmd1")
    assert result == ["cmd1"]
    out, _ = capsys.readouterr()
    assert "EOF" in out or "ended by user" in out

def test_validate_input_good_lines():
    assert input_modes.validate_input(["a", "b", "c"]) is True

def test_validate_input_fails_on_bad_type(caplog):
    with caplog.at_level("ERROR"):
        assert input_modes.validate_input(["a", 2]) is False
    assert "Invalid line type" in caplog.text

def test_validate_input_empty_warns(caplog):
    with caplog.at_level("WARNING"):
        assert input_modes.validate_input([]) is False
    assert "No input lines" in caplog.text

def test_format_final_input():
    assert input_modes.format_final_input(["one", "two"]) == "one\ntwo"

@pytest.mark.parametrize("line,mode", [
    ("hi \\", "backslash"),
    (";foo", "multi-command"),
    ("|cmd", "pipeline"),
    ("something else", "single"),
])
def test_determine_input_mode(line, mode):
    assert input_modes.determine_input_mode(line) == mode

def test_process_input_mode_invalid_mode_fallback():
    res = input_modes.process_input_mode("foo", "not-a-mode")
    assert res == ["foo"]

def test_process_input_mode_backslash(monkeypatch):
    called = {}
    monkeypatch.setattr(input_modes, "handle_backslash_continuation", lambda fl: called.setdefault("call", fl))
    input_modes.process_input_mode("foo \\", "backslash")
    assert called["call"] == "foo \\"

def test_process_input_mode_multi_command(monkeypatch):
    called = {}
    monkeypatch.setattr(input_modes, "handle_multi_command", lambda fl: called.setdefault("call", fl))
    input_modes.process_input_mode(";foo", "multi-command")
    assert called["call"] == ";foo"

def test_process_input_mode_pipeline(monkeypatch):
    called = {}
    monkeypatch.setattr(input_modes, "handle_pipeline_command", lambda fl: called.setdefault("call", fl))
    input_modes.process_input_mode("|foo", "pipeline")
    assert called["call"] == "|foo"

def test_process_input_mode_single(monkeypatch):
    called = {}
    monkeypatch.setattr(input_modes, "handle_single_line", lambda fl: called.setdefault("call", fl))
    input_modes.process_input_mode("foo", "single")
    assert called["call"] == "foo"



