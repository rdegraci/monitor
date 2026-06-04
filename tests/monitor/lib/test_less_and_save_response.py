"""Tests for the :less and :save_response built-ins.

Both surface the most recent assistant response from CONVERSATION_HISTORY
through a different output channel. Shared helper _last_assistant_response
walks history in reverse for the most recent assistant message with
non-empty content.

:less is TTY-sensitive — it falls back to plain print in --script mode
and in any non-TTY context (piped, redirected) so it never blocks the
bench runner waiting for a keystroke that won't come.
"""

import os
import subprocess
from unittest.mock import patch

import pytest

# Pre-import config to head off the known import-cycle.
import monitor.config  # noqa: F401

from monitor import config
from monitor.lib import built_in_commands


# ---------------------------------------------------------------------------
# _last_assistant_response: the shared helper
# ---------------------------------------------------------------------------


def test_last_response_returns_most_recent_assistant(monkeypatch):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2 — most recent"},
    ], raising=False)
    assert built_in_commands._last_assistant_response() == "a2 — most recent"


def test_last_response_skips_tool_calls_only_rounds(monkeypatch):
    """Assistant messages with no text content (just tool_calls) are
    dispatch rounds, not user-facing replies. :less / :save_response
    should walk past them to the most recent message that actually has
    text the user can read."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "the real answer"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "tool result"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
    ], raising=False)
    assert built_in_commands._last_assistant_response() == "the real answer"


def test_last_response_none_when_no_assistant_yet(monkeypatch):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ], raising=False)
    assert built_in_commands._last_assistant_response() is None


def test_last_response_none_when_history_unset(monkeypatch):
    """Right after startup the history may be missing/None — must not
    crash."""
    monkeypatch.delattr(config, "CONVERSATION_HISTORY", raising=False)
    assert built_in_commands._last_assistant_response() is None


# ---------------------------------------------------------------------------
# :less
# ---------------------------------------------------------------------------


def test_less_falls_back_to_print_when_not_a_tty(monkeypatch, capsys):
    """In --script mode and any piped/redirected stdout, isatty() is
    False — :less must NOT invoke rich's pager (would block forever) and
    instead just print the raw markdown. This is the load-bearing test
    for bench compatibility — without it, the bench runner would deadlock
    on every long response."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "the response"}
    ], raising=False)
    monkeypatch.setattr(built_in_commands.sys.stdout, "isatty", lambda: False)

    # If rich.Console gets touched in non-TTY mode something is wrong.
    # Patch the import-time symbols to raise so the test fails loudly.
    import rich.console as rich_console
    original_console = rich_console.Console

    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("rich.Console must not be constructed in non-TTY mode")

    monkeypatch.setattr(rich_console, "Console", fail_if_constructed)

    built_in_commands.less_command()
    captured = capsys.readouterr()
    assert "the response" in captured.out


def test_less_invokes_rich_pager_on_tty(monkeypatch):
    """On a TTY, :less wraps the text in Markdown(...) and prints it
    inside a Console().pager() context. Mock the pager to verify the
    flow without actually launching ``less`` (which would block the
    test runner waiting for keystrokes)."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "# Heading\n\n```python\nprint('hi')\n```\n"}
    ], raising=False)
    monkeypatch.setattr(built_in_commands.sys.stdout, "isatty", lambda: True)

    seen = {"pager_entered": False, "printed_objects": []}

    import contextlib
    import rich.console as rich_console
    import rich.markdown as rich_markdown

    class _FakeConsole:
        def __init__(self, *args, **kwargs):
            seen["console_init_kwargs"] = kwargs

        @contextlib.contextmanager
        def pager(self, **kwargs):
            seen["pager_entered"] = True
            seen["pager_kwargs"] = kwargs
            yield

        def print(self, obj, *args, **kwargs):
            seen["printed_objects"].append(obj)

    monkeypatch.setattr(rich_console, "Console", _FakeConsole)

    built_in_commands.less_command()

    assert seen["pager_entered"] is True
    # styles=True is the rich equivalent of less -R: lets ANSI styling
    # survive the pager pipe instead of being stripped to plain text.
    assert seen["pager_kwargs"].get("styles") is True
    assert len(seen["printed_objects"]) == 1
    # The printed object should be a Markdown instance — confirmation
    # that we're rendering markdown, not raw text.
    assert isinstance(seen["printed_objects"][0], rich_markdown.Markdown)


def test_less_handles_user_quitting_pager(monkeypatch):
    """BrokenPipeError fires when the user quits the pager before the
    full text was streamed in. Harmless — must not propagate."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "long text"}
    ], raising=False)
    monkeypatch.setattr(built_in_commands.sys.stdout, "isatty", lambda: True)

    import contextlib
    import rich.console as rich_console

    class _BrokenPipeConsole:
        def __init__(self, *args, **kwargs):
            pass

        @contextlib.contextmanager
        def pager(self, **kwargs):
            raise BrokenPipeError()
            yield  # unreachable, satisfies generator shape

        def print(self, *args, **kwargs):
            pass

    monkeypatch.setattr(rich_console, "Console", _BrokenPipeConsole)

    # Must not raise — that's the whole assertion.
    built_in_commands.less_command()


def test_less_degrades_to_print_on_rich_failure(monkeypatch, capsys):
    """If rich rendering or the pager subprocess explodes for any other
    reason (missing less binary, weird terminal, render bug), :less
    falls back to plain print rather than crashing the REPL."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "fallback content"}
    ], raising=False)
    monkeypatch.setattr(built_in_commands.sys.stdout, "isatty", lambda: True)

    import contextlib
    import rich.console as rich_console

    class _BrokenConsole:
        def __init__(self, *args, **kwargs):
            pass

        @contextlib.contextmanager
        def pager(self, **kwargs):
            raise RuntimeError("rich exploded")
            yield

        def print(self, *args, **kwargs):
            pass

    monkeypatch.setattr(rich_console, "Console", _BrokenConsole)

    built_in_commands.less_command()
    captured = capsys.readouterr()
    assert "fallback content" in captured.out


def test_less_with_no_response_prints_message(monkeypatch, capsys):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    built_in_commands.less_command()
    captured = capsys.readouterr()
    assert "No assistant response" in captured.out


def test_less_sets_LESS_R_inside_pager_and_restores_after(monkeypatch):
    """LESS=-R must be live while the pager runs (so less interprets
    ANSI codes instead of showing them as literal ESC[...m text) and
    restored to its prior value after — never leaking into the rest of
    the session.

    This test pins both halves: capture LESS inside pager(), then verify
    the post-:less env matches the pre-:less env exactly.
    """
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "x"}
    ], raising=False)
    monkeypatch.setattr(built_in_commands.sys.stdout, "isatty", lambda: True)

    # User had LESS set to something specific before invoking :less.
    # The expected post-state is exactly this — neither cleared nor
    # changed to -R.
    monkeypatch.setenv("LESS", "user-custom-value")

    seen = {"LESS_during": None}

    import contextlib
    import rich.console as rich_console

    class _ProbeConsole:
        def __init__(self, *args, **kwargs):
            pass

        @contextlib.contextmanager
        def pager(self, **kwargs):
            seen["LESS_during"] = os.environ.get("LESS")
            yield

        def print(self, *args, **kwargs):
            pass

    monkeypatch.setattr(rich_console, "Console", _ProbeConsole)

    built_in_commands.less_command()

    # Inside the pager: LESS was -R (so less interprets color escapes).
    assert seen["LESS_during"] == "-R"
    # After: LESS is restored to the user's pre-:less value.
    assert os.environ.get("LESS") == "user-custom-value"


def test_less_unsets_LESS_after_if_it_was_unset_before(monkeypatch):
    """The sentinel-pattern guarantee: if LESS wasn't set going in, it
    must NOT exist coming out — not even as an empty string. The
    distinction matters: any subprocess inspecting LESS would see
    different behavior depending on whether the var is absent vs set
    to empty."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "x"}
    ], raising=False)
    monkeypatch.setattr(built_in_commands.sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("LESS", raising=False)

    import contextlib
    import rich.console as rich_console

    class _NoopConsole:
        def __init__(self, *args, **kwargs):
            pass

        @contextlib.contextmanager
        def pager(self, **kwargs):
            yield

        def print(self, *args, **kwargs):
            pass

    monkeypatch.setattr(rich_console, "Console", _NoopConsole)

    built_in_commands.less_command()

    # The key invariant: LESS is GONE, not just set to "".
    assert "LESS" not in os.environ


def test_less_restores_LESS_even_when_pager_raises(monkeypatch):
    """The finally block is load-bearing: if the pager throws (broken
    pipe, missing less binary, rich render bug, anything), LESS=-R must
    NOT leak into the rest of the session. Without the finally guard,
    every subsequent subprocess in the same monitor3 process would
    inherit LESS=-R for the lifetime of the REPL."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "x"}
    ], raising=False)
    monkeypatch.setattr(built_in_commands.sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("LESS", "prior-value")

    import contextlib
    import rich.console as rich_console

    class _ExplodingConsole:
        def __init__(self, *args, **kwargs):
            pass

        @contextlib.contextmanager
        def pager(self, **kwargs):
            raise RuntimeError("boom")
            yield

        def print(self, *args, **kwargs):
            pass

    monkeypatch.setattr(rich_console, "Console", _ExplodingConsole)

    # Must not raise — the exception is caught and degraded to print.
    built_in_commands.less_command()

    # And LESS must be restored despite the explosion.
    assert os.environ.get("LESS") == "prior-value"


# ---------------------------------------------------------------------------
# :save_response
# ---------------------------------------------------------------------------


def test_save_response_no_arg_writes_to_cwd_with_default_name(monkeypatch, tmp_path):
    """No-arg call must produce response-<ts>.md inside the *current*
    working directory — that's what the help text promises."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "saved content"}
    ], raising=False)
    monkeypatch.chdir(tmp_path)

    built_in_commands.save_response_command()

    saved = list(tmp_path.glob("response-*.md"))
    assert len(saved) == 1, f"expected exactly one saved file, got {saved}"
    assert saved[0].read_text().rstrip("\n") == "saved content"


def test_save_response_directory_arg_uses_default_filename(monkeypatch, tmp_path):
    """If the arg points at an existing directory, save *into* it with
    the default response-<ts>.md filename. Treating a directory as if
    it were a filename would write a file with no extension, weird."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "into dir"}
    ], raising=False)
    subdir = tmp_path / "out"
    subdir.mkdir()

    built_in_commands.save_response_command(str(subdir))

    saved = list(subdir.glob("response-*.md"))
    assert len(saved) == 1
    assert saved[0].read_text().rstrip("\n") == "into dir"


def test_save_response_full_path_uses_path_exactly(monkeypatch, tmp_path):
    """When the arg is a non-existent path (interpreted as a target
    file, not a directory), it's used verbatim."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "exact path"}
    ], raising=False)
    target = tmp_path / "custom_name.md"

    built_in_commands.save_response_command(str(target))

    assert target.read_text().rstrip("\n") == "exact path"


def test_save_response_expands_user_home(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "tilde works"}
    ], raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    built_in_commands.save_response_command("~/response.md")

    assert (tmp_path / "response.md").read_text().rstrip("\n") == "tilde works"


def test_save_response_overwrites_existing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "new content"}
    ], raising=False)
    target = tmp_path / "out.md"
    target.write_text("stale content that should be replaced")

    built_in_commands.save_response_command(str(target))

    assert target.read_text().rstrip("\n") == "new content"


def test_save_response_rejects_missing_parent(monkeypatch, tmp_path, capsys):
    """Same rule as :dump_metrics / :dump_history — parent must exist.
    Refusing keeps the harness in charge of file layout."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "won't be written"}
    ], raising=False)
    bad = tmp_path / "no_such_dir" / "out.md"

    built_in_commands.save_response_command(str(bad))

    assert not bad.exists()
    out = capsys.readouterr()
    assert "Parent directory does not exist" in (out.out + out.err)


def test_save_response_no_response_prints_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    monkeypatch.chdir(tmp_path)

    built_in_commands.save_response_command()

    captured = capsys.readouterr()
    assert "No assistant response to save" in (captured.out + captured.err)
    # No file should have been created.
    assert list(tmp_path.glob("response-*.md")) == []


def test_save_response_appends_trailing_newline(monkeypatch, tmp_path):
    """A response without a trailing newline should still produce a
    POSIX-friendly file (POSIX defines a 'line' as text ending in \\n,
    so a missing trailing newline trips tools like grep/cat/diff)."""
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "assistant", "content": "no trailing newline"}
    ], raising=False)
    target = tmp_path / "out.md"

    built_in_commands.save_response_command(str(target))

    assert target.read_text().endswith("\n")


# ---------------------------------------------------------------------------
# Registration in the built-ins table
# ---------------------------------------------------------------------------


def test_less_and_save_response_are_registered_as_builtins():
    from monitor.core import built_ins
    from monitor.lib import built_ins_utils

    built_ins.configure_built_ins()

    names = [cmd.get("command") for cmd in built_ins_utils.built_in_functions]
    assert ":less" in names
    assert ":save_response" in names
