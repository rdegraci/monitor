"""Tests for the REASONING_BUMP_EFFORT floor helper.

higher_reasoning_effort raises an auto-bumped turn's effort to a configured
minimum without ever downgrading a higher bump (notably the tool-failure
escalation to "high"). These cover the floor/never-downgrade guarantee that the
conversation.py auto-bump and tooling.py escalation sites rely on.
"""

from monitor.lib.llm_model_utils import higher_reasoning_effort


def test_floor_raises_a_lower_bump():
    # Heuristic "medium" bump, configured floor "high" → raised to high.
    assert higher_reasoning_effort("medium", "high") == "high"
    assert higher_reasoning_effort("medium", "xhigh") == "xhigh"


def test_floor_never_downgrades():
    # Tool-failure "high" with a lower configured floor stays high.
    assert higher_reasoning_effort("high", "medium") == "high"
    assert higher_reasoning_effort("high", "low") == "high"
    assert higher_reasoning_effort("xhigh", "high") == "xhigh"


def test_equal_levels_unchanged():
    assert higher_reasoning_effort("high", "high") == "high"


def test_no_floor_returns_effort_unchanged():
    assert higher_reasoning_effort("medium", None) == "medium"
    assert higher_reasoning_effort("medium", "") == "medium"


def test_invalid_floor_ignored():
    assert higher_reasoning_effort("medium", "bogus") == "medium"
    assert higher_reasoning_effort("low", 3) == "low"


def test_unrecognized_effort_takes_valid_floor():
    # A bad effort label still gets pulled up to a valid configured floor.
    assert higher_reasoning_effort("bogus", "high") == "high"
    assert higher_reasoning_effort(None, "medium") == "medium"


def test_case_insensitive():
    assert higher_reasoning_effort("MEDIUM", "High") == "High"
    assert higher_reasoning_effort("HIGH", "medium") == "HIGH"
