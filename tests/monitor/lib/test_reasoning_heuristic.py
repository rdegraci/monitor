"""Tests for the per-turn reasoning auto-bump heuristic.

Covers:
- Each keyword signal fires the bump (whole-word for single words, substring
  for multi-word phrases).
- Word-boundary check prevents partial-word false positives.
- Length and line-count fallback signals.
- No-downgrade rule: never returns "medium" when default is already at or
  above medium.
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


@pytest.mark.parametrize(
    "phrase",
    [
        "root cause",
        "check for regressions",
        "trace through",
        "cross-file analysis",
        "audit the change",
        "across the codebase",
    ],
)
def test_multi_word_signals_fire_as_substrings(phrase):
    msg = f"please {phrase} before merging"
    assert detect_reasoning_bump(msg, "low") == "medium"


@pytest.mark.parametrize("word", ["debug"])
def test_single_word_signals_fire_as_whole_words(word):
    msg = f"please {word} the auth module"
    assert detect_reasoning_bump(msg, "low") == "medium"


def test_signal_match_case_sensitivity_matches_documented_behavior():
    """Multi-word phrases are lowercased before matching, so case variations
    should still fire. Single-word signals are word-boundary regex matches;
    title-case user wording should match, but all-caps macro-like tokens are
    intentionally not guaranteed to match."""
    assert detect_reasoning_bump("Please Root Cause this failure", "low") == "medium"
    assert detect_reasoning_bump("Please Check For Regressions in auth", "low") == "medium"
    assert detect_reasoning_bump("Debug the flaky test", "low") == "medium"
    assert detect_reasoning_bump("DEBUG the flaky test", "low") is None


def test_word_boundary_prevents_partial_word_false_positives():
    """Signals should not fire on partial-word matches.

    'debug' must not fire on 'debugging'.
    'trace' must not fire on 'traceback' or 'tracer'.
    'identify' must not fire on 'identifier'.
    Avoid separate keywords so the assertion isolates the word-boundary
    behavior under test.
    """
    assert detect_reasoning_bump("the debugging session is ongoing", "low") is None
    assert detect_reasoning_bump("print the traceback for the exception", "low") is None
    assert detect_reasoning_bump("the tracer bullet hit the target", "low") is None
    assert detect_reasoning_bump("rename the identifier field", "low") is None


def test_keyword_signals_include_representative_subset():
    """Regression: ensure representative signals from the current exported
    keyword list remain present."""
    expected_subset = {
        "debug",
        "trace",
        "investigate",
        "follow",
        "identify",
        "root cause",
        "check for regressions",
        "trace through",
        "cross-file analysis",
        "audit the change",
        "across the codebase",
    }
    assert expected_subset.issubset(set(KEYWORD_SIGNALS))


def test_keyword_signals_constant_matches_current_implementation():
    """Regression: keep the keyword list in sync with the implementation.
    If you change the signals, update this assertion intentionally."""
    assert set(KEYWORD_SIGNALS) == {
        "root cause",
        "what caused this",
        "why is this happening",
        "why did this break",
        "what is going wrong",
        "why is it failing",
        "where is this coming from",
        "how does this fail",
        "failure mode",
        "verify the fix",
        "check for regressions",
        "confirm the behavior",
        "validate the change",
        "make sure this is safe",
        "assess the risk",
        "ensure compatibility",
        "prove that",
        "is this correct",
        "trace through",
        "trace the flow",
        "follow the path",
        "investigate the issue",
        "inspect the call chain",
        "track down",
        "locate the source",
        "find the bug",
        "identify the regression",
        "pinpoint the problem",
        "cross-file analysis",
        "system-wide impact",
        "architecture review",
        "design review",
        "tradeoff analysis",
        "audit the change",
        "review for regressions",
        "examine the behavior",
        "look for edge cases",
        "check the assumptions",
        "evaluate correctness",
        "across the codebase",
        "interactions between",
        "behavioral change",
        "unexpected behavior",
        "debug",
        "trace",
        "investigate",
        "follow",
        "identify",
    }


# --- Length / line-count fallback -------------------------------------------


def test_long_message_triggers_bump():
    msg = "a" * (LENGTH_THRESHOLD + 1)
    assert detect_reasoning_bump(msg, "low") == "medium"


def test_message_at_length_threshold_does_not_trigger():
    """The check is strictly > THRESHOLD; equal-to is OK."""
    msg = "a" * LENGTH_THRESHOLD
    assert detect_reasoning_bump(msg, "low") is None


def test_multi_line_message_triggers():
    msg = "\n".join(["line"] * (LINE_COUNT_THRESHOLD + 1))
    assert detect_reasoning_bump(msg, "low") == "medium"


def test_short_message_with_no_signals_does_not_trigger():
    """The control case — routine one-liners should keep the default."""
    assert detect_reasoning_bump("typo on line 42", "low") is None
    assert detect_reasoning_bump("add a print statement", "low") is None
    assert detect_reasoning_bump("rename foo to bar", "low") is None


# --- No-downgrade invariant -------------------------------------------------


def test_high_default_returns_none():
    """If the user explicitly set their default above the bump target, the
    heuristic must not return anything — it can't justify a downgrade."""
    assert detect_reasoning_bump("please debug this across the codebase", "high") is None


def test_medium_default_returns_none():
    """If the default already matches the bump target, the heuristic is a no-op."""
    assert (
        detect_reasoning_bump("please debug this across the codebase", "medium")
        is None
    )


def test_xhigh_default_returns_none():
    """xhigh is above the bump target, so the heuristic must remain a no-op."""
    assert detect_reasoning_bump("please debug this across the codebase", "xhigh") is None


def test_unknown_default_treated_as_low_for_bumping():
    """Defensive: garbage current_effort should default to low-rank so
    we don't accidentally skip the bump."""
    assert detect_reasoning_bump("please audit the change", "garbage_value") == "medium"


def test_none_default_treated_as_low_for_bumping():
    assert detect_reasoning_bump("please debug this", None) == "medium"


# --- Floored bump target (REASONING_BUMP_EFFORT) ----------------------------


def test_bump_floor_raises_target_above_medium():
    """A floor lifts the returned target — a low default bumps straight to the
    floored level, not the default medium."""
    assert detect_reasoning_bump("please debug this", "low", bump_floor="high") == "high"
    assert (
        detect_reasoning_bump("please debug this", "low", bump_floor="xhigh")
        == "xhigh"
    )


def test_medium_default_with_higher_floor_now_fires():
    """The key new behavior: at steady medium, a higher floor opens the gate so
    the bump fires (to the floored target) instead of being a no-op."""
    assert (
        detect_reasoning_bump(
            "please cross-file analysis this change", "medium", bump_floor="high"
        )
        == "high"
    )


def test_medium_default_without_floor_still_noop():
    """No floor → target stays medium → steady medium is still a no-op (no
    spurious bump). Backward-compatible with the pre-floor behavior."""
    assert detect_reasoning_bump("please cross-file analysis this change", "medium") is None
    assert (
        detect_reasoning_bump(
            "please cross-file analysis this change", "medium", bump_floor=None
        )
        is None
    )


def test_floor_at_or_below_medium_does_not_lower_target():
    """A floor at/below medium can't drag the target below medium; a low default
    still bumps to medium."""
    assert detect_reasoning_bump("please audit the change", "low", bump_floor="low") == "medium"
    assert (
        detect_reasoning_bump("please audit the change", "low", bump_floor="medium")
        == "medium"
    )


def test_high_default_with_xhigh_floor_fires():
    """A floor above an already-high default reopens the gate (escalate high → xhigh)."""
    assert detect_reasoning_bump("please debug this", "high", bump_floor="xhigh") == "xhigh"


def test_high_default_with_high_floor_still_noop():
    """Floor equal to a high default → no headroom → no-op."""
    assert detect_reasoning_bump("please debug this", "high", bump_floor="high") is None


# --- Edge-case input handling -----------------------------------------------


def test_none_user_text_returns_none():
    assert detect_reasoning_bump(None, "low") is None


def test_empty_user_text_returns_none():
    assert detect_reasoning_bump("", "low") is None


def test_non_string_user_text_returns_none():
    assert detect_reasoning_bump(12345, "low") is None
    assert detect_reasoning_bump(["audit", "this"], "low") is None


# --- Override application at LLM call time ----------------------------------


def test_call_litellm_completion_uses_override_when_set(monkeypatch):
    """The override set by the heuristic must reach call_litellm_completion's
    kwargs so the LLM actually receives the bumped effort."""
    from monitor.lib import llm_utils
    from monitor import config

    monkeypatch.setattr(config, "REASONING_MODEL_PREFIX", "openai/gpt-5", raising=False)
    monkeypatch.setattr(config, "REASONING_EFFORT", "low", raising=False)
    monkeypatch.setattr(config, "REASONING_MAX_COMPLETION_TOKENS", 25000, raising=False)
    monkeypatch.setattr(config, "CURRENT_TURN_REASONING_OVERRIDE", "medium", raising=False)

    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        from unittest.mock import MagicMock

        return MagicMock()

    monkeypatch.setattr(llm_utils.litellm, "completion", fake_completion)

    llm_utils.call_litellm_completion(
        model="openai/gpt-5.4",
        messages=[{"role": "user", "content": "audit the change"}],
        tool_descriptions=[],
        gemini_tool_descriptions=[],
    )

    # Override beats default — kwargs should reflect "medium".
    assert captured.get("reasoning_effort") == "medium"


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
