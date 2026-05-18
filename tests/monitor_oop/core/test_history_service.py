"""Tests for the isolated Monitor OOP history service."""
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.models import Message


def test_history_service_append_and_trim() -> None:
    """Verify history append and trim behavior."""

    service = HistoryService(ConfigService())
    service.append(Message(role="user", content="one"))
    service.append(Message(role="assistant", content="two"))
    service.append(Message(role="user", content="three"))

    service.trim(2)

    snapshot = service.snapshot()

    assert len(snapshot) == 2
    assert snapshot[0].content == "two"
    assert snapshot[1].content == "three"


def test_history_service_reset_with_summary() -> None:
    """Verify reset with summary seeds a system message."""

    service = HistoryService(ConfigService())

    service.reset_with_summary("summary text")

    snapshot = service.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0].role == "system"
    assert snapshot[0].content == "summary text"


class _StubConfig:
    def __init__(self, conversation_max_turns: int) -> None:
        self.conversation_max_turns = conversation_max_turns

    def get_conversation_turn_budget(self) -> int:
        return self.conversation_max_turns


class _SoftRatioStubConfig:
    """Config stub that exposes both the turn budget and a soft-ratio accessor."""

    def __init__(
        self,
        conversation_max_turns: int,
        soft_ratio: float | None,
    ) -> None:
        self._conversation_max_turns = conversation_max_turns
        self._soft_ratio = soft_ratio

    def get_conversation_turn_budget(self) -> int:
        return self._conversation_max_turns

    def get_compaction_soft_ratio(self) -> float | None:
        return self._soft_ratio


class _StubCompactionStore:
    def __init__(self) -> None:
        self.persisted_summaries: list[str] = []

    def persist_summary(self, summary_text: str) -> None:
        self.persisted_summaries.append(summary_text)


def test_history_service_compact_changes_large_history() -> None:
    """Verify compact changes history once the history is large enough."""

    compaction_store = _StubCompactionStore()
    service = HistoryService(_StubConfig(conversation_max_turns=2), compaction_store=compaction_store)

    service.append(Message(role="user", content="one"))
    service.append(Message(role="assistant", content="two"))
    service.append(Message(role="user", content="three"))
    service.append(Message(role="assistant", content="four"))

    before_snapshot = service.snapshot()

    summary_text = "summary text"
    service.compact(summary_text)

    snapshot = service.snapshot()

    assert snapshot != before_snapshot
    assert snapshot[0].role == "system"
    assert snapshot[0].content == summary_text
    assert snapshot[-2].role == "user"
    assert snapshot[-2].content == "three"
    assert snapshot[-1].role == "assistant"
    assert snapshot[-1].content == "four"
    assert compaction_store.persisted_summaries == [summary_text]


def test_history_service_compact_for_small_history() -> None:
    """Verify compact still compacts a small fixed history."""

    compaction_store = _StubCompactionStore()
    service = HistoryService(_StubConfig(conversation_max_turns=1), compaction_store=compaction_store)

    service.append(Message(role="user", content="one"))
    service.append(Message(role="assistant", content="two"))

    service.compact("summary text")

    snapshot = service.snapshot()

    assert snapshot[0].role == "system"
    assert snapshot[0].content == "summary text"
    assert compaction_store.persisted_summaries == ["summary text"]


def test_history_service_compact_preserves_recent_messages() -> None:
    """Verify compaction keeps recent messages and summarizes older history."""

    compaction_store = _StubCompactionStore()
    service = HistoryService(_StubConfig(conversation_max_turns=2), compaction_store=compaction_store)

    service.append(Message(role="user", content="one"))
    service.append(Message(role="assistant", content="two"))
    service.append(Message(role="user", content="three"))
    service.append(Message(role="assistant", content="four"))

    summary_text = "summary text"
    service.compact(summary_text)

    snapshot = service.snapshot()

    assert snapshot[0].role == "system"
    assert snapshot[0].content == summary_text
    assert snapshot[-2].role == "user"
    assert snapshot[-2].content == "three"
    assert snapshot[-1].role == "assistant"
    assert snapshot[-1].content == "four"
    assert compaction_store.persisted_summaries == [summary_text]


def test_history_service_compact_preserves_plain_messages() -> None:
    """Verify plain messages survive the compaction path without metadata requirements."""

    compaction_store = _StubCompactionStore()
    service = HistoryService(_StubConfig(conversation_max_turns=2), compaction_store=compaction_store)

    service.append(Message(role="user", content="plain user"))
    service.append(Message(role="assistant", content="plain assistant"))
    service.append(Message(role="user", content="extra user"))

    summary_text = "deterministic summary"
    service.compact(summary_text)

    snapshot = service.snapshot()

    assert snapshot[0].role == "system"
    assert snapshot[0].content == summary_text
    assert any(message.role == "user" and message.content == "plain user" for message in snapshot)
    assert any(message.role == "assistant" and message.content == "plain assistant" for message in snapshot)
    assert next(i for i, message in enumerate(snapshot) if message.role == "user" and message.content == "plain user") < next(
        i for i, message in enumerate(snapshot) if message.role == "assistant" and message.content == "plain assistant"
    )
    assert compaction_store.persisted_summaries == [summary_text]


def test_should_compact_fires_soft_trigger_at_ratio_threshold() -> None:
    """Verify the soft branch fires when input tokens reach ratio * context_window."""

    service = HistoryService(_SoftRatioStubConfig(conversation_max_turns=128, soft_ratio=0.5))

    # context_window=1000, soft_threshold=500. input=500 should fire (>=).
    assert service.should_compact(
        context_window=1000,
        estimated_token_count=500,
        output_window=200,
    ) is True


def test_should_compact_does_not_fire_soft_trigger_below_threshold() -> None:
    """Verify the soft branch stays quiet when input tokens are under the soft threshold."""

    service = HistoryService(_SoftRatioStubConfig(conversation_max_turns=128, soft_ratio=0.5))

    # context_window=1000, soft_threshold=500. input=300 should NOT fire soft;
    # input + output = 500 < 1000 so hard also stays quiet.
    assert service.should_compact(
        context_window=1000,
        estimated_token_count=300,
        output_window=200,
    ) is False


def test_should_compact_disabled_soft_ratio_falls_back_to_hard_check() -> None:
    """Verify soft_ratio=None disables the soft branch; hard backstop still works."""

    service = HistoryService(_SoftRatioStubConfig(conversation_max_turns=128, soft_ratio=None))

    # input=600 would have fired the soft branch at 0.5; with soft disabled,
    # only the hard check applies: 600 + 200 = 800 < 1000 → no compaction.
    assert service.should_compact(
        context_window=1000,
        estimated_token_count=600,
        output_window=200,
    ) is False

    # Hard threshold reached: 800 + 200 = 1000 ≥ 1000 → compaction.
    assert service.should_compact(
        context_window=1000,
        estimated_token_count=800,
        output_window=200,
    ) is True


def test_should_compact_out_of_range_soft_ratio_disables_soft_branch() -> None:
    """Verify ratios outside (0, 1) disable the soft branch defensively."""

    for ratio in (0.0, 1.0, -0.5, 2.0):
        service = HistoryService(
            _SoftRatioStubConfig(conversation_max_turns=128, soft_ratio=ratio)
        )

        # input=600 with context=1000 would fire soft at 0.5; with ratio
        # outside (0, 1) soft is disabled, hard is 800 < 1000 → False.
        assert service.should_compact(
            context_window=1000,
            estimated_token_count=600,
            output_window=200,
        ) is False, f"soft branch must be disabled for ratio={ratio}"
