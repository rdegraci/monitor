"""Tests for tool-body demotion in monitor.lib.history.

Covers:
- demote_old_tool_bodies: edge cases (empty, k<=0, history too short),
  correct boundary placement, idempotency via sentinel, MIN_BODY_SIZE
  threshold respected, return count accurate.
- _demote_tool_result_content: small contents skipped, large contents
  rewritten with sentinel + size hint, idempotent.
- _demote_assistant_tool_call_arguments: parses JSON args, rewrites large
  string fields, re-serializes; malformed JSON left alone; non-dict args
  left alone.
"""

import json
import logging

import pytest

# Pre-import config to break the known import cycle (see
# test_partial_compaction.py for the same workaround).
import monitor.config  # noqa: F401

from monitor.lib.history import (
    DEMOTION_SENTINEL,
    MIN_BODY_SIZE_TO_DEMOTE,
    _demote_assistant_tool_call_arguments,
    _demote_tool_result_content,
    demote_old_tool_bodies,
)


def _user(content="hi"):
    return {"role": "user", "content": content}


def _assistant_tool_call(call_id, fn_name, args_dict):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": fn_name,
                    "arguments": json.dumps(args_dict),
                },
            }
        ],
    }


def _tool_result(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


# --- _demote_tool_result_content --------------------------------------------


def test_tool_result_demoted_when_over_threshold():
    msg = _tool_result("t1", "x" * (MIN_BODY_SIZE_TO_DEMOTE + 50))
    original_size = len(msg["content"])
    assert _demote_tool_result_content(msg) is True
    assert msg["content"].startswith(DEMOTION_SENTINEL)
    assert str(original_size) in msg["content"]


def test_tool_result_small_content_skipped():
    msg = _tool_result("t1", "x" * (MIN_BODY_SIZE_TO_DEMOTE - 1))
    snapshot = msg["content"]
    assert _demote_tool_result_content(msg) is False
    assert msg["content"] == snapshot  # untouched


def test_tool_result_already_demoted_is_idempotent():
    msg = _tool_result("t1", f"{DEMOTION_SENTINEL} 9999 chars already removed.")
    snapshot = msg["content"]
    assert _demote_tool_result_content(msg) is False
    assert msg["content"] == snapshot


def test_tool_result_non_string_content_skipped():
    """Defensive: some providers may return structured content. Don't try
    to demote what we can't safely measure."""
    msg = {"role": "tool", "tool_call_id": "t1", "content": [{"type": "text", "text": "x"}]}
    assert _demote_tool_result_content(msg) is False


# --- _demote_assistant_tool_call_arguments ----------------------------------


def test_tool_call_arguments_bulky_string_demoted():
    msg = _assistant_tool_call(
        "t1",
        "text_file_str_replace_in_file",
        {
            "path": "foo.py",                                 # small, kept
            "old_str": "x" * (MIN_BODY_SIZE_TO_DEMOTE + 50),  # large, demoted
            "new_str": "x" * (MIN_BODY_SIZE_TO_DEMOTE + 50),  # large, demoted
        },
    )
    assert _demote_assistant_tool_call_arguments(msg) is True
    args = json.loads(msg["tool_calls"][0]["function"]["arguments"])
    assert args["path"] == "foo.py"  # small string preserved
    assert args["old_str"].startswith("[demoted:")
    assert "old_str" in args["old_str"]  # key name in placeholder for clarity
    assert args["new_str"].startswith("[demoted:")


def test_tool_call_arguments_all_small_skipped():
    msg = _assistant_tool_call("t1", "fn", {"k1": "small", "k2": "also small"})
    snapshot = msg["tool_calls"][0]["function"]["arguments"]
    assert _demote_assistant_tool_call_arguments(msg) is False
    assert msg["tool_calls"][0]["function"]["arguments"] == snapshot


def test_tool_call_arguments_malformed_json_skipped():
    """Garbage in the arguments string must not be rewritten or crash the
    helper — leave it visible so the upstream bug is diagnosable."""
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "t1",
                "type": "function",
                "function": {"name": "fn", "arguments": "this is not json"},
            }
        ],
    }
    snapshot = msg["tool_calls"][0]["function"]["arguments"]
    assert _demote_assistant_tool_call_arguments(msg) is False
    assert msg["tool_calls"][0]["function"]["arguments"] == snapshot


def test_tool_call_arguments_non_dict_parsed_skipped():
    """If arguments JSON parses to something other than a dict (e.g., a
    list), there are no key/value pairs to demote — leave it alone."""
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "t1",
                "type": "function",
                "function": {"name": "fn", "arguments": json.dumps(["x" * 1000])},
            }
        ],
    }
    assert _demote_assistant_tool_call_arguments(msg) is False


def test_tool_call_arguments_no_tool_calls_array_skipped():
    msg = {"role": "assistant", "content": "regular reply, no tool calls"}
    assert _demote_assistant_tool_call_arguments(msg) is False


def test_tool_call_arguments_already_demoted_is_idempotent():
    """The sentinel is added INSIDE the args dict on individual values, not
    as a prefix on the JSON string — so we can't use the string-prefix
    idempotency check. The per-value length check handles it: a placeholder
    value like "[demoted: 1000 chars omitted from `new_str`]" is short
    enough to fall under MIN_BODY_SIZE_TO_DEMOTE on the second pass."""
    msg = _assistant_tool_call(
        "t1", "fn", {"big": "x" * (MIN_BODY_SIZE_TO_DEMOTE + 100)}
    )
    assert _demote_assistant_tool_call_arguments(msg) is True
    first_args = msg["tool_calls"][0]["function"]["arguments"]
    # Second pass — should be a no-op because the placeholder is too short
    # to qualify for further demotion.
    assert _demote_assistant_tool_call_arguments(msg) is False
    assert msg["tool_calls"][0]["function"]["arguments"] == first_args


# --- demote_old_tool_bodies (top-level walker) ------------------------------


def test_walker_returns_zero_for_empty_history():
    assert demote_old_tool_bodies([], 3) == 0


def test_walker_returns_zero_for_zero_or_negative_k():
    history = [_user(), _user()]
    assert demote_old_tool_bodies(history, 0) == 0
    assert demote_old_tool_bodies(history, -1) == 0


def test_walker_returns_zero_when_history_shorter_than_threshold():
    """With K=3 and only 2 user messages, nothing is "old enough" to
    demote — everything is still recent."""
    history = [
        _user("u1"),
        _tool_result("t1", "x" * 5000),
        _user("u2"),
    ]
    assert demote_old_tool_bodies(history, 3) == 0
    # Tool result must be untouched.
    assert not history[1]["content"].startswith(DEMOTION_SENTINEL)


def test_walker_demotes_only_past_boundary():
    """K=1: only the last user turn is "recent." Everything before the
    last user message should be demoted; everything from it onward
    untouched."""
    history = [
        _user("u1"),
        _assistant_tool_call("c1", "fn", {"big": "x" * 1000}),
        _tool_result("c1", "y" * 1000),
        _user("u2"),  # boundary — preserve from here
        _assistant_tool_call("c2", "fn", {"big": "z" * 1000}),
        _tool_result("c2", "w" * 1000),
    ]
    count = demote_old_tool_bodies(history, 1)
    assert count == 2  # one assistant tool_call args + one tool result

    # Old portion demoted.
    assert json.loads(history[1]["tool_calls"][0]["function"]["arguments"])["big"].startswith("[demoted:")
    assert history[2]["content"].startswith(DEMOTION_SENTINEL)

    # Recent portion untouched.
    assert json.loads(history[4]["tool_calls"][0]["function"]["arguments"])["big"] == "z" * 1000
    assert history[5]["content"] == "w" * 1000


def test_walker_is_idempotent_on_second_pass():
    """Running demotion twice should rewrite nothing the second time —
    the sentinel makes already-demoted messages skip on subsequent passes,
    keeping the cached prefix stable across turns."""
    history = [
        _user("u1"),
        _tool_result("c1", "x" * 1000),
        _user("u2"),
    ]
    first = demote_old_tool_bodies(history, 1)
    second = demote_old_tool_bodies(history, 1)
    assert first == 1
    assert second == 0  # no new work on the second pass


def test_walker_returns_count_of_rewritten_messages():
    history = [
        _user("u1"),
        _tool_result("c1", "a" * 1000),
        _tool_result("c2", "b" * 1000),
        _assistant_tool_call("c3", "fn", {"big": "c" * 1000}),
        _user("u2"),
    ]
    assert demote_old_tool_bodies(history, 1) == 3


def test_walker_ignores_non_dict_entries():
    history = [
        "garbage",
        _user("u1"),
        None,
        _tool_result("c1", "x" * 1000),
        _user("u2"),
    ]
    # Doesn't crash; demotes the one valid tool result past the boundary.
    assert demote_old_tool_bodies(history, 1) == 1
