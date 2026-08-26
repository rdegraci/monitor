import argparse
from types import SimpleNamespace

import pytest

from monitor.app import (
    _load_prompt_text,
    _prompt_mode_requested,
    _validate_prompt_mode_args,
    run_prompt,
)
from monitor.core.conversation import ConversationResult


def test_prompt_mode_requested():
    assert _prompt_mode_requested(SimpleNamespace(prompt="hi", prompt_file=None)) is True
    assert _prompt_mode_requested(SimpleNamespace(prompt=None, prompt_file="file.txt")) is True
    assert _prompt_mode_requested(SimpleNamespace(prompt=None, prompt_file=None)) is False


def test_validate_prompt_mode_rejects_both_sources():
    parser = argparse.ArgumentParser()
    args = SimpleNamespace(
        prompt="hi",
        prompt_file="file.txt",
        script=None,
        tui=False,
        server=None,
    )
    with pytest.raises(SystemExit):
        _validate_prompt_mode_args(parser, args)


def test_validate_prompt_mode_rejects_script_conflict():
    parser = argparse.ArgumentParser()
    args = SimpleNamespace(
        prompt="hi",
        prompt_file=None,
        script="cmds.txt",
        tui=False,
        server=None,
    )
    with pytest.raises(SystemExit):
        _validate_prompt_mode_args(parser, args)


def test_load_prompt_text_from_flag():
    args = SimpleNamespace(prompt="  hello world  ", prompt_file=None)
    text, error = _load_prompt_text(args)
    assert error is None
    assert text == "hello world"


def test_load_prompt_text_rejects_blank_flag():
    args = SimpleNamespace(prompt="   ", prompt_file=None)
    text, error = _load_prompt_text(args)
    assert text is None
    assert "non-empty" in error


def test_load_prompt_text_from_file(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("line one\nline two\n", encoding="utf-8")
    args = SimpleNamespace(prompt=None, prompt_file=str(path))
    text, error = _load_prompt_text(args)
    assert error is None
    assert text == "line one\nline two"


def test_load_prompt_text_from_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", SimpleNamespace(read=lambda: "from stdin\n"))
    args = SimpleNamespace(prompt=None, prompt_file="-")
    text, error = _load_prompt_text(args)
    assert error is None
    assert text == "from stdin"


def test_run_prompt_prints_plain_stdout(capsys, monkeypatch):
    monkeypatch.setattr("monitor.app.register_query_function", lambda func: None)
    monkeypatch.setattr("monitor.app._initialize_prompt_history", lambda: None)
    monkeypatch.setattr(
        "monitor.app.conversation_query",
        lambda prompt: "assistant answer",
    )

    rc = run_prompt("user question")

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "assistant answer\n"
    assert captured.err == ""


def test_run_prompt_error_exit_code(capsys, monkeypatch):
    monkeypatch.setattr("monitor.app.register_query_function", lambda func: None)
    monkeypatch.setattr("monitor.app._initialize_prompt_history", lambda: None)
    monkeypatch.setattr(
        "monitor.app.conversation_query",
        lambda prompt: ConversationResult.ERROR,
    )

    rc = run_prompt("user question")

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "Prompt query failed" in captured.err


def test_run_prompt_empty_result_exit_code(capsys, monkeypatch):
    monkeypatch.setattr("monitor.app.register_query_function", lambda func: None)
    monkeypatch.setattr("monitor.app._initialize_prompt_history", lambda: None)
    monkeypatch.setattr("monitor.app.conversation_query", lambda prompt: "   ")

    rc = run_prompt("user question")

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "returned no text" in captured.err
