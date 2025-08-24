import pytest
from unittest.mock import patch
from monitor.lib import input_modes

class FakeSession:
    def __init__(self, script):
        self._iter = iter(script)
    def prompt(self, *args, **kwargs):
        val = next(self._iter)
        if isinstance(val, BaseException):
            raise val
        return val

def test_handle_single_line_returns_line():
    assert input_modes.handle_single_line("hi there") == ["hi there"]

def test_handle_multi_command_reads_until_eof():
    session = FakeSession(["foo", "bar", "EOF"])
    result = input_modes.handle_multi_command(";first", session=session)
    assert result == ["first;;;", "foo;;;", "bar;;;"]

def test_handle_multi_command_eoferror(capsys):
    session = FakeSession([EOFError()])
    result = input_modes.handle_multi_command(";first", session=session)
    assert result == ["first;;;"]
    out, _ = capsys.readouterr()
    assert "EOF" in out

def test_handle_backslash_continuation_reads_until_eof():
    session = FakeSession(["line1", "EOF"])
    lines = input_modes.handle_backslash_continuation("hello \\", session=session)
    assert lines == ["!<hello ", "!<line1"]

def test_handle_backslash_continuation_eoferror(capsys):
    session = FakeSession([EOFError()])
    lines = input_modes.handle_backslash_continuation("hi \\", session=session)
    assert lines == ["!<hi "]
    out, _ = capsys.readouterr()
    assert "EOF" in out

def test_handle_pipeline_collect_single_and_multi():
    session = FakeSession([
        "simple-one",
        "alpha\\",
        "beta\\",
        "gamma",
        "EOL",
        "simple-two",
        "EOF",
        "Y",
    ])
    result = input_modes.handle_pipeline_command("|cmd-first", session=session)
    assert result == ["cmd-first", "simple-one", "alpha\nbeta\\\ngamma", "simple-two"]
    assert len(result) == 4

def test_pipeline_escaped_markers_and_literal_backslash():
    session = FakeSession([
        "\\EOL\\",
        "\\EOF",
        "ends with backslash \\",
        "EOL",
        "EOF",
        "Y",
    ])
    result = input_modes.handle_pipeline_command("|cmd", session=session)
    assert result == ["cmd", "\\EOL\n\\EOF\nends with backslash \\"]

def test_pipeline_blank_lines_ignored_outside_included_inside():
    session = FakeSession([
        "",
        "inside 1\\",
        "",
        "EOL",
        "",
        "EOF",
        "Y",
    ])
    result = input_modes.handle_pipeline_command("|cmd", session=session)
    assert result == ["cmd", "inside 1\n"]

def test_pipeline_ctrl_c_outside_exits_without_processing():
    session = FakeSession([KeyboardInterrupt()])
    result = input_modes.handle_pipeline_command("|cmd", session=session)
    assert result == []

def test_pipeline_ctrl_c_inside_cancels_block_and_continues():
    session = FakeSession([
        "partial line\\",
        KeyboardInterrupt(),
        "after",
        "EOF",
        "Y",
    ])
    result = input_modes.handle_pipeline_command("|cmd", session=session)
    assert result == ["cmd", "after"]

def test_pipeline_eof_inside_block_finalizes():
    session = FakeSession([
        "block line\\",
        "EOF",
        "",
    ])
    result = input_modes.handle_pipeline_command("|cmd", session=session)
    assert result == ["cmd", "block line"]

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
    monkeypatch.setattr(input_modes, "handle_backslash_continuation", lambda fl, session=None: called.setdefault("call", fl))
    input_modes.process_input_mode("foo \\", "backslash")
    assert called["call"] == "foo \\"

def test_process_input_mode_multi_command(monkeypatch):
    called = {}
    monkeypatch.setattr(input_modes, "handle_multi_command", lambda fl, session=None: called.setdefault("call", fl))
    input_modes.process_input_mode(";foo", "multi-command")
    assert called["call"] == ";foo"

def test_process_input_mode_pipeline(monkeypatch):
    called = {}
    monkeypatch.setattr(input_modes, "handle_pipeline_command", lambda fl, session=None: called.setdefault("call", fl))
    input_modes.process_input_mode("|foo", "pipeline")
    assert called["call"] == "|foo"

def test_process_input_mode_single(monkeypatch):
    called = {}
    monkeypatch.setattr(input_modes, "handle_single_line", lambda fl, session=None: called.setdefault("call", fl))
    input_modes.process_input_mode("foo", "single")
    assert called["call"] == "foo"
