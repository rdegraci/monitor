import os
import sys
import subprocess

# Ensure the src directory is on sys.path so we can import the package under test
_tests_dir = os.path.dirname(__file__)
_src_dir = os.path.abspath(os.path.join(_tests_dir, "..", "src"))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import pytest

pygments_lexers = pytest.importorskip("pygments.lexers")
BashLexer = pygments_lexers.BashLexer

import monitor.lib.git_utils as git_utils


def test_ensure_non_empty_string_valid():
    assert git_utils.ensure_non_empty_string("  hello ", "Name") == "hello"


def test_ensure_non_empty_string_invalid_empty():
    with pytest.raises(ValueError):
        git_utils.ensure_non_empty_string("   ", "Name")


def test_ensure_non_empty_string_invalid_type():
    with pytest.raises(ValueError):
        git_utils.ensure_non_empty_string(None, "Name")


def test_run_git_capture_success(monkeypatch):
    # Simulate subprocess.run returning a CompletedProcess with stdout/stderr
    def fake_run(cmd_args, check, text, capture_output):
        return subprocess.CompletedProcess(cmd_args, 0, stdout="ok-output", stderr="err-output")

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)

    stdout, stderr, error = git_utils.run_git_capture(["git", "status"])
    assert stdout == "ok-output"
    assert stderr == "err-output"
    assert error is None


def test_run_git_capture_failure(monkeypatch):
    # Simulate subprocess.run raising CalledProcessError
    def fake_run(cmd_args, check, text, capture_output):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd_args, output="fail-output")

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)

    stdout, stderr, error = git_utils.run_git_capture(["git", "status"])
    assert stdout is None and stderr is None
    assert isinstance(error, str)
    assert "An error occurred while executing" in error


def test_highlight_text_returns_string():
    # Ensure highlight_text produces a string for given input and lexer
    text = "echo hi"
    highlighted = git_utils.highlight_text(text, BashLexer())
    assert isinstance(highlighted, str)
    assert len(highlighted) > 0
    # raw content should be present somewhere in the highlighted output
    assert "echo" in highlighted


def test_print_highlight_or_empty_non_empty(monkeypatch, capsys):
    # Replace highlight_text to make output deterministic
    monkeypatch.setattr(git_utils, "highlight_text", lambda text, lexer: f"HIGHLIGHT:{text}")

    git_utils.print_highlight_or_empty("some text", None, "Empty")
    captured = capsys.readouterr()
    assert "HIGHLIGHT:some text" in captured.out


def test_print_highlight_or_empty_empty(monkeypatch, capsys):
    # Ensure the empty message is printed when text is empty
    git_utils.print_highlight_or_empty("", None, "No content")
    captured = capsys.readouterr()
    assert "No content" in captured.out
