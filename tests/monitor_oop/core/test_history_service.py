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


class _StubCompactionStore:
    def __init__(self) -> None:
        self.persisted_summaries: list[str] = []

    def persist_summary(self, summary_text: str) -> None:
        self.persisted_summaries.append(summary_text)


def test_history_service_should_compact_tracks_user_turns() -> None:
    """Verify turn tracking becomes compacting once the configured threshold is reached."""

    service = HistoryService(_StubConfig(conversation_max_turns=2))

    service.append(Message(role="user", content="turn-0"))

    assert not service.should_compact()

    service.append(Message(role="assistant", content="turn-1"))

    assert not service.should_compact()

    service.append(Message(role="user", content="turn-2"))

    assert service.should_compact()


def test_history_service_turn_budget_tracker_resets_on_clear() -> None:
    """Verify the explicit turn budget tracker stays in sync with appended user messages and resets on clear."""

    service = HistoryService(_StubConfig(conversation_max_turns=2))

    service.append(Message(role="user", content="one"))
    service.append(Message(role="assistant", content="two"))

    assert not service.should_compact()

    service.append(Message(role="user", content="three"))

    assert service.should_compact()

    service.clear()

    assert not service.should_compact()

    service.append(Message(role="assistant", content="four"))
    service.append(Message(role="user", content="five"))

    assert not service.should_compact()

    service.append(Message(role="user", content="six"))

    assert service.should_compact()


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


def test_history_service_compact_with_summary_preserves_plain_messages() -> None:
    """Verify plain messages survive the compaction path without metadata requirements."""

    compaction_store = _StubCompactionStore()
    service = HistoryService(_StubConfig(conversation_max_turns=2), compaction_store=compaction_store)

    service.append(Message(role="user", content="plain user"))
    service.append(Message(role="assistant", content="plain assistant"))
    service.append(Message(role="user", content="extra user"))

    summary_text = "deterministic summary"
    result = service.compact_with_summary(summary_text)

    snapshot = service.snapshot()

    assert result is True
    assert snapshot[0].role == "system"
    assert snapshot[0].content == summary_text
    assert any(message.role == "user" and message.content == "plain user" for message in snapshot)
    assert any(message.role == "assistant" and message.content == "plain assistant" for message in snapshot)
    assert next(i for i, message in enumerate(snapshot) if message.role == "user" and message.content == "plain user") < next(
        i for i, message in enumerate(snapshot) if message.role == "assistant" and message.content == "plain assistant"
    )
    assert compaction_store.persisted_summaries == [summary_text]
