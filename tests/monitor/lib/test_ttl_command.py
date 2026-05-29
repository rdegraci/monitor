"""Tests for the :ttl built-in (Anthropic prompt-cache TTL configuration) and
the corresponding system-message cache_control plumbing.

Coverage:
- ttl_command valid integer values (5, 60) update config.ANTHROPIC_CACHE_TTL.
- ttl_command with no arg, "help", non-int, or out-of-range int prints help
  and does NOT change config.
- prepare_messages_with_cache_control honors config.ANTHROPIC_CACHE_TTL for
  the system breakpoint, and KEEPS the final-user-message breakpoint at 5m
  (no ttl field) regardless of config — that breakpoint moves every turn so
  a long TTL adds write cost without saving anything.
"""

import pytest

from monitor import config as cfg
from monitor.lib.built_in_commands import ttl_command
from monitor.lib.message_utils import prepare_messages_with_cache_control


# --- ttl_command ------------------------------------------------------------


def test_ttl_command_sets_5m(monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "1h", raising=False)
    ttl_command("5")
    assert cfg.ANTHROPIC_CACHE_TTL == "5m"


def test_ttl_command_sets_1h(monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "5m", raising=False)
    ttl_command("60")
    assert cfg.ANTHROPIC_CACHE_TTL == "1h"


def test_ttl_command_no_arg_shows_help_without_mutating(capsys, monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "1h", raising=False)
    ttl_command(None)
    out = capsys.readouterr().out
    assert "Usage: :ttl <minutes>" in out
    assert "Current TTL: 60 minutes" in out
    assert cfg.ANTHROPIC_CACHE_TTL == "1h"  # unchanged


def test_ttl_command_help_keyword_shows_help(capsys, monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "5m", raising=False)
    ttl_command("help")
    out = capsys.readouterr().out
    assert "Usage: :ttl <minutes>" in out
    assert "Current TTL: 5 minutes" in out
    assert cfg.ANTHROPIC_CACHE_TTL == "5m"  # unchanged


def test_ttl_command_rejects_non_integer(capsys, monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "1h", raising=False)
    ttl_command("abc")
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Could not parse" in combined
    assert "Usage: :ttl <minutes>" in combined
    assert cfg.ANTHROPIC_CACHE_TTL == "1h"  # unchanged


def test_ttl_command_rejects_unsupported_minute_value(capsys, monkeypatch):
    """Anthropic only supports 5m and 1h. Other ints must be rejected — silently
    accepting them would result in an API rejection at request time, with the
    user unable to tell what they configured wrong."""
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "1h", raising=False)
    ttl_command("30")
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Invalid value: 30" in combined
    assert cfg.ANTHROPIC_CACHE_TTL == "1h"  # unchanged


# --- prepare_messages_with_cache_control TTL plumbing ------------------------


def _anthropic_model():
    return "anthropic/claude-opus-4-7"


def test_system_breakpoint_uses_configured_ttl_1h(monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "1h", raising=False)
    msgs = [
        {"role": "system", "content": "you are a coding assistant"},
        {"role": "user", "content": "hi"},
    ]
    out = prepare_messages_with_cache_control(msgs, _anthropic_model())
    assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_system_breakpoint_uses_configured_ttl_5m(monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "5m", raising=False)
    msgs = [
        {"role": "system", "content": "you are a coding assistant"},
        {"role": "user", "content": "hi"},
    ]
    out = prepare_messages_with_cache_control(msgs, _anthropic_model())
    # 5m is Anthropic's documented default; we omit the ttl field rather than
    # send "5m" explicitly to keep the payload minimal.
    assert out[0]["cache_control"] == {"type": "ephemeral"}
    assert "ttl" not in out[0]["cache_control"]


def test_final_user_breakpoint_stays_at_5m_regardless_of_config(monkeypatch):
    """The final-user-message breakpoint shifts every turn (it points at the
    new user input). A long TTL there is pure write-cost overhead. Verify it
    stays at the 5m default even when ANTHROPIC_CACHE_TTL is set to 1h."""
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "1h", raising=False)
    msgs = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "first turn"},
        {"role": "assistant", "content": "response"},
        {"role": "user", "content": "second turn"},
    ]
    out = prepare_messages_with_cache_control(msgs, _anthropic_model())
    # System gets long TTL.
    assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # Final user keeps short default.
    assert out[-1]["cache_control"] == {"type": "ephemeral"}
    assert "ttl" not in out[-1]["cache_control"]


def test_non_anthropic_model_skips_all_cache_control(monkeypatch):
    monkeypatch.setattr(cfg, "ANTHROPIC_CACHE_TTL", "1h", raising=False)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    out = prepare_messages_with_cache_control(msgs, "openai/gpt-5.4-mini")
    assert all("cache_control" not in m for m in out)
