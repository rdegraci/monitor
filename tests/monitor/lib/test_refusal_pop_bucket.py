"""Test for the refusal-pop bucket symmetry fix.

When the model refuses to respond (finish_reason in {refusal, content_filter,
safety}), the harness pops the last user message from CONVERSATION_HISTORY
to keep the conversation in a sendable shape. Pre-fix, the per-turn cost
bucket opened by that user message stayed in TURN_COSTS_USD, leaving a
phantom $0.00 entry that surfaced as a misleading last-turn cost in the
U: indicator.

This test pins the symmetric pop: when the user message goes, its bucket
goes with it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import monitor.config  # noqa: F401 — break import cycle


def _make_response(finish_reason):
    """Build a minimal response object the way the LLM client provides one,
    just enough to drive the refusal branch of process_response_by_finish_reason."""
    choice = SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content="", tool_calls=None),
    )
    return SimpleNamespace(choices=[choice])


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch):
    """Each refusal test mutates config conversation ledgers; isolate them."""
    monkeypatch.setattr(monitor.config, "CONVERSATION_HISTORY", [], raising=False)
    monkeypatch.setattr(monitor.config, "TURN_COSTS_USD", [], raising=False)
    monkeypatch.setattr(monitor.config, "TURN_ROUND_TRIPS", [], raising=False)
    yield


def test_refusal_pops_user_bucket_in_lockstep_with_user_message():
    """The key invariant being fixed: the per-turn cost bucket opened when
    the refused user message landed gets popped together with the user
    message. Pre-fix: TURN_COSTS_USD kept the orphan 0.0 bucket and the
    U: indicator showed a phantom $0.00 last-turn forever.

    Note: the existing refusal handler also pops a trailing assistant
    message if one is now at the tail (a separate quirk — that assistant
    msg is the *prior* turn's reply, not anything refusal-related). That
    behavior is preserved as-is; only the bucket-pop is being added in
    lockstep with the user-message pop."""
    from monitor.lib.llm_utils import process_response_by_finish_reason

    monitor.config.CONVERSATION_HISTORY[:] = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply 1"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "reply 2"},
        # New user message that's about to be refused — bucket exists with 0.
        {"role": "user", "content": "asks something refused"},
    ]
    monitor.config.TURN_COSTS_USD[:] = [0.12, 0.18, 0.0]
    monitor.config.TURN_ROUND_TRIPS[:] = [1, 2, 0]

    process_response_by_finish_reason(_make_response("refusal"))

    # Bucket invariant: the orphan 0.0 bucket is popped. Prior bucket costs
    # are untouched.
    assert monitor.config.TURN_COSTS_USD == [0.12, 0.18]
    assert monitor.config.TURN_ROUND_TRIPS == [1, 2]


def test_content_filter_refusal_also_pops_bucket():
    """grok uses 'content_filter' as the refusal finish_reason; the symmetry
    must hold for that path too."""
    from monitor.lib.llm_utils import process_response_by_finish_reason

    monitor.config.CONVERSATION_HISTORY[:] = [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "prev reply"},
        {"role": "user", "content": "filtered"},
    ]
    monitor.config.TURN_COSTS_USD[:] = [0.05, 0.0]
    monitor.config.TURN_ROUND_TRIPS[:] = [1, 0]

    process_response_by_finish_reason(_make_response("content_filter"))

    assert monitor.config.TURN_COSTS_USD == [0.05]
    assert monitor.config.TURN_ROUND_TRIPS == [1]


def test_safety_refusal_also_pops_bucket():
    """gemini uses 'safety' — same symmetry."""
    from monitor.lib.llm_utils import process_response_by_finish_reason

    monitor.config.CONVERSATION_HISTORY[:] = [
        {"role": "user", "content": "unsafe"},
    ]
    monitor.config.TURN_COSTS_USD[:] = [0.0]
    monitor.config.TURN_ROUND_TRIPS[:] = [0]

    process_response_by_finish_reason(_make_response("safety"))

    assert monitor.config.TURN_COSTS_USD == []
    assert monitor.config.TURN_ROUND_TRIPS == []


def test_no_pop_when_history_doesnt_end_in_user_message():
    """Defensive: if the last message isn't role=user (already cleaned up
    by some other path), don't pop a bucket. The bucket list is the source
    of truth for past costs and we must not silently lose entries."""
    from monitor.lib.llm_utils import process_response_by_finish_reason

    monitor.config.CONVERSATION_HISTORY[:] = [
        {"role": "user", "content": "asked"},
        {"role": "assistant", "content": "partial reply"},
    ]
    monitor.config.TURN_COSTS_USD[:] = [0.42]
    monitor.config.TURN_ROUND_TRIPS[:] = [1]

    process_response_by_finish_reason(_make_response("refusal"))

    # Bucket cost preserved because no user message was popped — the
    # refusal handler only pops if last message is role=user.
    assert monitor.config.TURN_COSTS_USD == [0.42]
    assert monitor.config.TURN_ROUND_TRIPS == [1]


def test_empty_bucket_list_pop_is_safe():
    """Defensive: if for some reason TURN_COSTS_USD is empty when a refusal
    pops a user message, don't crash. The handler should swallow the pop
    quietly — display formatting will recover naturally."""
    from monitor.lib.llm_utils import process_response_by_finish_reason

    monitor.config.CONVERSATION_HISTORY[:] = [{"role": "user", "content": "x"}]
    # Bucket list is empty (out-of-sync with history).
    monitor.config.TURN_COSTS_USD[:] = []
    monitor.config.TURN_ROUND_TRIPS[:] = [0]

    # Must not raise.
    process_response_by_finish_reason(_make_response("refusal"))
    assert monitor.config.TURN_COSTS_USD == []
    assert monitor.config.TURN_ROUND_TRIPS == []
