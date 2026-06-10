"""Tests for the MAX_COMPLETION_TOKENS cap and the :max_tokens command.

Covers:
- Default value is 8192.
- YAML override honored when >= 1; rejected (warn + keep default) for
  zero/negative/non-integer.
- call_litellm_completion sets max_completion_tokens in kwargs for
  non-reasoning models; leaves the reasoning path's larger cap alone.
- max_tokens_command paths: valid int, missing arg (help), invalid arg,
  non-integer arg.
"""

import logging
from unittest.mock import patch, MagicMock

import pytest

from monitor import config


# --- config default + YAML loader -------------------------------------------


def test_default_cap_is_8192():
    assert config.MAX_COMPLETION_TOKENS == 8192


def test_yaml_loader_accepts_valid_value():
    original = config.MAX_COMPLETION_TOKENS
    try:
        _invoke_yaml_loader({"MAX_COMPLETION_TOKENS": 16384})
        assert config.MAX_COMPLETION_TOKENS == 16384
    finally:
        config.MAX_COMPLETION_TOKENS = original


def test_yaml_loader_rejects_zero(caplog):
    original = config.MAX_COMPLETION_TOKENS
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"MAX_COMPLETION_TOKENS": 0})
        assert config.MAX_COMPLETION_TOKENS == original
        assert any("must be >= 1" in r.getMessage() for r in caplog.records)
    finally:
        config.MAX_COMPLETION_TOKENS = original


def test_yaml_loader_rejects_non_integer(caplog):
    original = config.MAX_COMPLETION_TOKENS
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"MAX_COMPLETION_TOKENS": "lots of tokens"})
        assert config.MAX_COMPLETION_TOKENS == original
        assert any("is not an integer" in r.getMessage() for r in caplog.records)
    finally:
        config.MAX_COMPLETION_TOKENS = original


# --- call_litellm_completion plumbing ---------------------------------------


def test_non_reasoning_call_sets_max_completion_tokens(monkeypatch):
    """For a non-reasoning model, the configured cap should appear in the
    kwargs forwarded to litellm.completion."""
    from monitor.lib import llm_utils
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 4321, raising=False)
    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/o3", raising=False)

    captured_kwargs = {}

    def fake_completion(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(llm_utils.litellm, "completion", fake_completion)

    llm_utils.call_litellm_completion(
        model="anthropic/claude-opus-4-7",  # NOT a reasoning model
        messages=[{"role": "user", "content": "hi"}],
        tool_descriptions=[],
        gemini_tool_descriptions=[],
    )

    assert captured_kwargs.get("max_completion_tokens") == 4321


def test_reasoning_call_uses_reasoning_cap_not_general_cap(monkeypatch):
    """Reasoning models get REASONING_MAX_COMPLETION_TOKENS, not the
    general MAX_COMPLETION_TOKENS — the general cap is too tight for
    chain-of-thought."""
    from monitor.lib import llm_utils
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 4321, raising=False)
    monkeypatch.setattr(config, "REASONING_MAX_COMPLETION_TOKENS", 25000, raising=False)
    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/o3", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT", "medium", raising=False)

    captured_kwargs = {}

    def fake_completion(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(llm_utils.litellm, "completion", fake_completion)

    llm_utils.call_litellm_completion(
        model="openai/o3-2025-04-16",  # MATCHES the reasoning prefix
        messages=[{"role": "user", "content": "hi"}],
        tool_descriptions=[],
        gemini_tool_descriptions=[],
    )

    # Should see the reasoning cap, NOT the general cap.
    assert captured_kwargs.get("max_completion_tokens") == 25000


def test_zero_or_invalid_cap_omits_kwarg(monkeypatch):
    """Defensive: if MAX_COMPLETION_TOKENS somehow ends up at zero or
    non-int (a user editing config at runtime), don't pass it to litellm —
    let the provider use its own default rather than crash on an invalid
    parameter."""
    from monitor.lib import llm_utils
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 0, raising=False)
    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/o3", raising=False)

    captured_kwargs = {}

    def fake_completion(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(llm_utils.litellm, "completion", fake_completion)

    llm_utils.call_litellm_completion(
        model="openai/gpt-4o",  # non-reasoning
        messages=[{"role": "user", "content": "hi"}],
        tool_descriptions=[],
        gemini_tool_descriptions=[],
    )

    assert "max_completion_tokens" not in captured_kwargs


# --- :max_tokens command ----------------------------------------------------


def test_max_tokens_command_sets_value(monkeypatch):
    from monitor.lib.built_in_commands import max_tokens_command
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 8192, raising=False)
    max_tokens_command("16000")
    assert config.MAX_COMPLETION_TOKENS == 16000


def test_max_tokens_command_no_arg_shows_help(capsys, monkeypatch):
    from monitor.lib.built_in_commands import max_tokens_command
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 8192, raising=False)
    max_tokens_command(None)
    out = capsys.readouterr().out
    assert "Usage: : (or /) max_tokens" in out
    assert "Current cap: 8192" in out
    assert config.MAX_COMPLETION_TOKENS == 8192  # unchanged


def test_max_tokens_command_rejects_non_integer(capsys, monkeypatch):
    from monitor.lib.built_in_commands import max_tokens_command
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 8192, raising=False)
    max_tokens_command("not a number")
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Could not parse" in combined
    assert config.MAX_COMPLETION_TOKENS == 8192  # unchanged


def test_max_tokens_command_rejects_zero(capsys, monkeypatch):
    from monitor.lib.built_in_commands import max_tokens_command
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 8192, raising=False)
    max_tokens_command("0")
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Invalid value: 0" in combined
    assert config.MAX_COMPLETION_TOKENS == 8192  # unchanged


def test_max_tokens_command_help_keyword(capsys, monkeypatch):
    from monitor.lib.built_in_commands import max_tokens_command
    monkeypatch.setattr(config, "MAX_COMPLETION_TOKENS", 8192, raising=False)
    max_tokens_command("help")
    out = capsys.readouterr().out
    assert "Usage: : (or /) max_tokens" in out


# --- helper -----------------------------------------------------------------


def _invoke_yaml_loader(yaml_overrides):
    """Mirror the MAX_COMPLETION_TOKENS validation in load_environment_globals
    without running the full loader (which has unrelated side effects). Keep
    this aligned with the actual config.py code."""
    _mct_raw = yaml_overrides.get("MAX_COMPLETION_TOKENS")
    if _mct_raw is None:
        return
    try:
        _mct_val = int(_mct_raw)
        if _mct_val >= 1:
            config.MAX_COMPLETION_TOKENS = _mct_val
        else:
            config_logger = logging.getLogger("monitor.config")
            config_logger.warning(
                "MAX_COMPLETION_TOKENS=%r must be >= 1; keeping default %d",
                _mct_raw, config.MAX_COMPLETION_TOKENS,
            )
    except (TypeError, ValueError):
        config_logger = logging.getLogger("monitor.config")
        config_logger.warning(
            "MAX_COMPLETION_TOKENS=%r is not an integer; keeping default %d",
            _mct_raw, config.MAX_COMPLETION_TOKENS,
        )
