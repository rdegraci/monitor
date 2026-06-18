"""Tests for the per-turn reasoning auto-bump heuristic.

Covers:
- Each keyword signal fires the bump (whole-word for single words, substring
  for multi-word phrases).
- Word-boundary check prevents partial-word false positives ("alignment"
  doesn't trigger "align").
- Length and line-count fallback signals.
- No-downgrade rule: never returns "high" when default is already at or
  above high.
- Empty / None input handling.
- LLM call integration: override-or-default is read at call time, the
  override wins when set, otherwise the configured default applies.
"""

import pytest

# Pre-import config to break the import cycle for tests touching history.
import monitor.config  # noqa: F401

from monitor.lib.reasoning_heuristic import (
    KEYWORD_SIGNALS,
    LENGTH_THRESHOLD,
    LINE_COUNT_THRESHOLD,
    detect_reasoning_bump,
)


@pytest.fixture(autouse=True)
def _reset_override():
    """The override is a per-turn config global; tests that mutate it must
    clean up to avoid leaking state into the next test (especially the
    pre-existing call_litellm_completion tests that read REASONING_EFFORT
    directly and would see a stray override otherwise)."""
    from monitor import config as _config
    _config.CURRENT_TURN_REASONING_OVERRIDE = None
    yield
    _config.CURRENT_TURN_REASONING_OVERRIDE = None


# --- Keyword signals --------------------------------------------------------


@pytest.mark.parametrize("word", [
    "refactor", "audit", "design", "analyze", "debug",
    "architecture", "cross-file", "migrate", "align", "why",
])
def test_single_word_signals_fire(word):
    msg = f"please {word} the auth module"
    assert detect_reasoning_bump(msg, "medium") == "high"


def test_multi_word_signal_fires_as_substring():
    """'review for' is a phrase, not a single token — substring match
    rather than word-boundary."""
    assert detect_reasoning_bump("please review for race conditions", "medium") == "high"


def test_signal_match_is_case_insensitive():
    assert detect_reasoning_bump("AUDIT the whole codebase", "medium") == "high"
    assert detect_reasoning_bump("Why does this fail?", "medium") == "high"


def test_word_boundary_prevents_partial_word_false_positives():
    """Signals should not fire on partial-word matches.

    'align' must not fire on 'alignment' or 'aligned'.
    'why' must not fire on 'anywhere' or 'pathways'.
    Avoid separate keywords like 'fix' so the assertion isolates the
    word-boundary behavior under test.
    """
    assert detect_reasoning_bump("adjust the alignment of the header", "medium") is None
    assert detect_reasoning_bump("the rows are aligned correctly", "medium") is None
    assert detect_reasoning_bump("does the answer live anywhere", "medium") is None
    assert detect_reasoning_bump("update the pathways constant", "medium") is None


def test_keyword_signals_constant_matches_documented_list():
    """Regression: keep the keyword list in sync with the README / docs.
    If you change the signals, update this assertion intentionally."""
    assert set(KEYWORD_SIGNALS) == {
        "refactor", "audit", "design", "review for", "analyze",
        "debug", "architecture", "cross-file", "migrate", "align", "why",
        "examine", "trace", "verify", "fix",
    }


# --- Length / line-count fallback -------------------------------------------


def test_long_message_triggers_bump():
    msg = "a" * (LENGTH_THRESHOLD + 1)
    assert detect_reasoning_bump(msg, "medium") == "high"


def test_message_at_length_threshold_does_not_trigger():
    """The check is strictly > THRESHOLD; equal-to is OK."""
    msg = "a" * LENGTH_THRESHOLD
    assert detect_reasoning_bump(msg, "medium") is None


def test_multi_line_message_triggers():
    msg = "\n".join(["line"] * (LINE_COUNT_THRESHOLD + 1))
    assert detect_reasoning_bump(msg, "medium") == "high"


def test_short_message_with_no_signals_does_not_trigger():
    """The control case — routine one-liners should keep the default."""
    assert detect_reasoning_bump("typo on line 42", "medium") is None
    assert detect_reasoning_bump("add a print statement", "medium") is None
    assert detect_reasoning_bump("rename foo to bar", "medium") is None


# --- No-downgrade invariant -------------------------------------------------


def test_high_default_returns_none():
    """If the user explicitly set their default to high (or above), the
    heuristic must not return anything — it can't go higher."""
    assert detect_reasoning_bump("please refactor this entire architecture", "high") is None


def test_xhigh_default_returns_none():
    """xhigh is above high, so the bump heuristic must remain a no-op."""
    assert detect_reasoning_bump("please refactor this entire architecture", "xhigh") is None


def test_unknown_default_treated_as_medium():
    """Defensive: garbage current_effort should default to medium-rank so
    we don't accidentally skip the bump."""
    assert detect_reasoning_bump("please audit the security", "garbage_value") == "high"


def test_none_default_treated_as_medium():
    assert detect_reasoning_bump("please debug this", None) == "high"


# --- Edge-case input handling -----------------------------------------------


def test_none_user_text_returns_none():
    assert detect_reasoning_bump(None, "medium") is None


def test_empty_user_text_returns_none():
    assert detect_reasoning_bump("", "medium") is None


def test_non_string_user_text_returns_none():
    assert detect_reasoning_bump(12345, "medium") is None
    assert detect_reasoning_bump(["audit", "this"], "medium") is None


# --- Override application at LLM call time ----------------------------------


def test_call_litellm_completion_uses_override_when_set(monkeypatch):
    """The override set by the heuristic must reach call_litellm_completion's
    kwargs so the LLM actually receives the bumped effort."""
    from monitor.lib import llm_utils
    from monitor import config

    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/gpt-5", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT", "medium", raising=False)
    monkeypatch.setattr(config, "REASONING_MAX_COMPLETION_TOKENS", 25000, raising=False)
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", "high", raising=False)

    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        from unittest.mock import MagicMock
        return MagicMock()

    monkeypatch.setattr(llm_utils.litellm, "completion", fake_completion)

    llm_utils.call_litellm_completion(
        model="openai/gpt-5.4",
        messages=[{"role": "user", "content": "audit this"}],
        tool_descriptions=[],
        gemini_tool_descriptions=[],
    )

    # Override beats default — kwargs should reflect "high".
    assert captured.get("reasoning_effort") == "high"


def test_call_litellm_completion_falls_back_to_default_without_override(monkeypatch):
    from monitor.lib import llm_utils
    from monitor import config

    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/gpt-5", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT", "medium", raising=False)
    monkeypatch.setattr(config, "REASONING_MAX_COMPLETION_TOKENS", 25000, raising=False)
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", None, raising=False)

    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        from unittest.mock import MagicMock
        return MagicMock()

    monkeypatch.setattr(llm_utils.litellm, "completion", fake_completion)

    llm_utils.call_litellm_completion(
        model="openai/gpt-5.4",
        messages=[{"role": "user", "content": "anything"}],
        tool_descriptions=[],
        gemini_tool_descriptions=[],
    )

    # No override → default ("medium") applies.
    assert captured.get("reasoning_effort") == "medium"
