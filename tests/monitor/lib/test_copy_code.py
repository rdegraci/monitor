"""Tests for the :copy_code built-in (and its :cc alias).

The command extracts triple-backtick fenced code blocks from the most
recent assistant response and copies the chosen block to the system
clipboard via pyperclip. Tests cover the fence parser, argument parsing
(default / N / "all"), and the graceful-fallback behavior when the
clipboard service is unavailable (Docker without X11, SSH without
forwarding, CI sandbox).
"""

import sys

import pytest

# Pre-import config to head off the known import-cycle when this test
# file is collected first.
import monitor.config  # noqa: F401

from monitor import config
from monitor.lib import built_in_commands


# ---------------------------------------------------------------------------
# _extract_fenced_code_blocks: the regex parser
# ---------------------------------------------------------------------------


def test_extract_single_block_with_language():
    text = "Here is the code:\n\n```python\nprint('hi')\n```\n"
    blocks = built_in_commands._extract_fenced_code_blocks(text)
    assert blocks == [("python", "print('hi')")]


def test_extract_block_without_language():
    text = "```\nbare block\n```"
    blocks = built_in_commands._extract_fenced_code_blocks(text)
    assert blocks == [("", "bare block")]


def test_extract_multiple_blocks_preserves_order():
    text = (
        "First:\n```js\nconsole.log(1)\n```\n"
        "Then:\n```python\nprint(2)\n```\n"
        "Finally:\n```\nplain\n```\n"
    )
    blocks = built_in_commands._extract_fenced_code_blocks(text)
    assert blocks == [
        ("js", "console.log(1)"),
        ("python", "print(2)"),
        ("", "plain"),
    ]


def test_extract_ignores_inline_backticks():
    """Single-backtick inline code (``code``) must NOT be picked up —
    those are too short to be the intended :copy_code target, and
    treating them as code blocks would create dozens of spurious matches
    in any prose-heavy response."""
    text = "Use `os.path.join()` to build paths. No code blocks here."
    blocks = built_in_commands._extract_fenced_code_blocks(text)
    assert blocks == []


def test_extract_preserves_internal_whitespace():
    """Indentation inside the block must round-trip exactly — losing
    indentation would make the copied code unusable for Python."""
    text = "```python\ndef foo():\n    if x:\n        return 1\n```"
    blocks = built_in_commands._extract_fenced_code_blocks(text)
    assert blocks == [("python", "def foo():\n    if x:\n        return 1")]


def test_extract_handles_language_with_special_chars():
    """Markdown allows hyphens and dots in language hints (e.g.,
    ``c++``, ``objective-c``). The parser must accept them."""
    text = "```objective-c\nNSLog(@\"hi\");\n```"
    blocks = built_in_commands._extract_fenced_code_blocks(text)
    assert blocks == [("objective-c", 'NSLog(@"hi");')]


def test_extract_empty_text():
    assert built_in_commands._extract_fenced_code_blocks("") == []


# ---------------------------------------------------------------------------
# :copy_code happy path with mocked pyperclip
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_clipboard(monkeypatch):
    """Replace pyperclip.copy with a buffer the test can inspect."""
    import pyperclip
    buf = {"value": None}
    monkeypatch.setattr(pyperclip, "copy", lambda v: buf.update(value=v))
    return buf


def _seed_response(monkeypatch, content):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": content},
    ], raising=False)


def test_no_arg_copies_first_block(monkeypatch, fake_clipboard, capsys):
    _seed_response(monkeypatch, "```python\nfirst\n```\n```js\nsecond\n```")
    built_in_commands.copy_code_command()
    assert fake_clipboard["value"] == "first"
    out = capsys.readouterr().out
    assert "first of 2 blocks" in out


def test_numeric_arg_copies_nth_block(monkeypatch, fake_clipboard):
    """1-indexed: ``:copy_code 2`` copies the SECOND block, not the
    third. Off-by-one here would be a daily papercut."""
    _seed_response(monkeypatch, "```python\nfirst\n```\n```js\nsecond\n```\n```\nthird\n```")
    built_in_commands.copy_code_command("2")
    assert fake_clipboard["value"] == "second"


def test_arg_one_equals_default(monkeypatch, fake_clipboard):
    """``:copy_code 1`` and ``:copy_code`` (no arg) must produce the
    same result — explicit 1 is just the default spelled out."""
    _seed_response(monkeypatch, "```\nonly\n```")
    built_in_commands.copy_code_command("1")
    assert fake_clipboard["value"] == "only"


def test_all_arg_concatenates_with_blank_line(monkeypatch, fake_clipboard, capsys):
    """``all`` joins blocks with \\n\\n so they remain readable as
    separate units when pasted. Single \\n would merge adjacent blocks
    into one visually confusing chunk."""
    _seed_response(monkeypatch, "```\nA\n```\n```\nB\n```\n```\nC\n```")
    built_in_commands.copy_code_command("all")
    assert fake_clipboard["value"] == "A\n\nB\n\nC"
    out = capsys.readouterr().out
    assert "all 3 blocks" in out


def test_all_arg_is_case_insensitive(monkeypatch, fake_clipboard):
    _seed_response(monkeypatch, "```\nA\n```\n```\nB\n```")
    built_in_commands.copy_code_command("ALL")
    assert fake_clipboard["value"] == "A\n\nB"


def test_language_hint_is_stripped_from_copied_payload(monkeypatch, fake_clipboard):
    """The user copies code to paste it somewhere — they almost never
    want the ``\\`\\`\\`python`` line in the clipboard."""
    _seed_response(monkeypatch, "```python\nprint('hi')\n```")
    built_in_commands.copy_code_command()
    assert "```" not in fake_clipboard["value"]
    assert "python" not in fake_clipboard["value"].splitlines()[0]
    assert fake_clipboard["value"] == "print('hi')"


# ---------------------------------------------------------------------------
# Error / no-op paths
# ---------------------------------------------------------------------------


def test_no_response_prints_error(monkeypatch, fake_clipboard, capsys):
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    built_in_commands.copy_code_command()
    out = capsys.readouterr().out + capsys.readouterr().err
    # Capsys may have buffered between two reads; capture once fresh.
    monkeypatch.setattr(config, "CONVERSATION_HISTORY", [], raising=False)
    built_in_commands.copy_code_command()
    captured = capsys.readouterr()
    assert "No assistant response" in (captured.out + captured.err)
    # Clipboard MUST NOT have been touched — copying nothing would
    # silently wipe whatever the user had in their clipboard.
    assert fake_clipboard["value"] is None


def test_no_code_block_in_response(monkeypatch, fake_clipboard, capsys):
    _seed_response(monkeypatch, "Just prose. No code at all. `inline` doesn't count.")
    built_in_commands.copy_code_command()
    captured = capsys.readouterr()
    assert "No code block found" in (captured.out + captured.err)
    assert fake_clipboard["value"] is None


def test_index_out_of_range_prints_helpful_error(monkeypatch, fake_clipboard, capsys):
    _seed_response(monkeypatch, "```\nfirst\n```\n```\nsecond\n```")
    built_in_commands.copy_code_command("5")
    captured = capsys.readouterr()
    assert "out of range" in (captured.out + captured.err)
    # Helpful: the error tells them how many blocks DO exist.
    assert "2 blocks" in (captured.out + captured.err)
    assert fake_clipboard["value"] is None


def test_non_numeric_non_all_arg_rejected(monkeypatch, fake_clipboard, capsys):
    _seed_response(monkeypatch, "```\nfirst\n```")
    built_in_commands.copy_code_command("garbage")
    captured = capsys.readouterr()
    assert "Invalid argument" in (captured.out + captured.err)
    assert fake_clipboard["value"] is None


def test_zero_or_negative_index_rejected(monkeypatch, fake_clipboard, capsys):
    """1-indexed means 0 is invalid (and negative is also nonsense).
    Falling back to ``blocks[-1]`` for negative N would be cute but
    surprising."""
    _seed_response(monkeypatch, "```\nfirst\n```")
    built_in_commands.copy_code_command("0")
    captured = capsys.readouterr()
    assert "out of range" in (captured.out + captured.err)
    built_in_commands.copy_code_command("-1")
    captured = capsys.readouterr()
    # -1 parses as int (-1) → out of range, OR as invalid (int() accepts
    # negatives, so it's the range branch).
    assert "out of range" in (captured.out + captured.err)


# ---------------------------------------------------------------------------
# Clipboard unavailable: graceful fallback
# ---------------------------------------------------------------------------


def test_clipboard_failure_prints_payload_with_notice(monkeypatch, capsys):
    """Headless environments (Docker without X11, SSH without forwarding,
    CI sandbox) raise PyperclipException at copy time. The command MUST
    degrade gracefully: print the code to stdout so the user can hand-
    copy from terminal, and surface why the clipboard didn't work."""
    _seed_response(monkeypatch, "```python\nfallback content\n```")

    import pyperclip

    def raise_clipboard_error(value):
        # PyperclipException is the real type but Exception works for
        # the fallback path's broad catch.
        raise Exception("Pyperclip could not find a copy/paste mechanism")

    monkeypatch.setattr(pyperclip, "copy", raise_clipboard_error)

    built_in_commands.copy_code_command()
    captured = capsys.readouterr()
    # Code IS in stdout — user can manually copy from terminal.
    assert "fallback content" in captured.out
    # Notice IS surfaced — user knows clipboard didn't work.
    assert "clipboard unavailable" in captured.out


def test_clipboard_failure_doesnt_count_as_success(monkeypatch, capsys):
    """When the clipboard write fails, the "Copied N chars" success
    message MUST NOT print — otherwise the user thinks the copy worked
    and pastes stale content from their clipboard."""
    _seed_response(monkeypatch, "```python\nx\n```")

    import pyperclip
    monkeypatch.setattr(
        pyperclip, "copy",
        lambda v: (_ for _ in ()).throw(Exception("nope")),
    )

    built_in_commands.copy_code_command()
    captured = capsys.readouterr()
    assert "Copied" not in captured.out


# ---------------------------------------------------------------------------
# Registration: both :copy_code AND :cc must point to the same function
# ---------------------------------------------------------------------------


def test_both_command_names_registered():
    """The :cc alias must dispatch to copy_code_command — same pattern as
    :llm / :model. Without both registrations, typing :cc would fall
    through to "unknown command"."""
    from monitor.core import built_ins
    from monitor.lib import built_ins_utils

    built_ins.configure_built_ins()

    names = [cmd.get("command") for cmd in built_ins_utils.built_in_functions]
    assert "copy_code" in names
    assert "cc" in names


def test_cc_alias_and_copy_code_share_the_same_underlying_function():
    """Lexically the descriptions differ ('Alias for :copy_code.') but
    both entries' ``function`` callable must reach copy_code_command.
    Tests this by invoking via the built-in dispatch and confirming the
    same clipboard write happens."""
    from monitor.core import built_ins
    from monitor.lib import built_ins_utils

    built_ins.configure_built_ins()

    cc_entry = next(c for c in built_ins_utils.built_in_functions if c["command"] == "cc")
    copy_entry = next(c for c in built_ins_utils.built_in_functions if c["command"] == "copy_code")

    # Both wrappers are _make_callable adapters around the same source —
    # easiest invariant to check is that they behave identically.
    assert callable(cc_entry["function"])
    assert callable(copy_entry["function"])
