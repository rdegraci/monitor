"""Tests for the isolated Monitor OOP conversation session."""
from pathlib import Path

import appdirs
from prompt_toolkit.history import FileHistory

from monitor_oop.core.command_processor import CommandProcessor
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.conversation_session import ConversationSession
from monitor_oop.core.history_service import HistoryService
from monitor_oop.core.llm_service import LLMService
from monitor_oop.core.macro_service import MacroService
from monitor_oop.core.models import CommandType
from monitor_oop.core.prompt_service import PromptService
from monitor_oop.core.infrastructure.prompt_store import PromptStore
from monitor_oop.core.runtime_context import RuntimeContext
from monitor_oop.core.status_service import StatusService


def build_session() -> ConversationSession:
    """Build a conversation session for tests."""

    config_service = ConfigService()
    history_service = HistoryService(config_service)
    macro_service = MacroService(config_service)
    status_service = StatusService()
    llm_service = LLMService(config_service)
    prompt_store = PromptStore(config_service)
    prompt_service = PromptService(prompt_store)
    command_processor = CommandProcessor(
        config_service,
        history_service,
        macro_service,
        status_service,
    )
    context = RuntimeContext(
        config_service=config_service,
        history_service=history_service,
        macro_service=macro_service,
        status_service=status_service,
        command_processor=command_processor,
        llm_service=llm_service,
        prompt_service=prompt_service,
    )
    return ConversationSession(context)


def test_conversation_session_start_sets_running() -> None:
    """Verify session start updates state."""

    session = build_session()

    assert session.start() == 0
    assert session.is_running is True
    assert session.context.state.running is True


def test_read_user_input_uses_prompt_session(monkeypatch) -> None:
    """Verify user input comes from prompt_toolkit with history."""

    session = build_session()
    prompt_calls = {}
    created_sessions = []

    class MockPromptSession:
        def __init__(self, *, history) -> None:
            prompt_calls["history"] = history
            created_sessions.append(self)

        def prompt(self, *args, **kwargs) -> str:
            prompt_calls["args"] = args
            prompt_calls["kwargs"] = kwargs
            return "hello"

    monkeypatch.setattr(
        "monitor_oop.core.conversation_session.PromptSession",
        MockPromptSession,
    )

    history_dir = Path(appdirs.user_config_dir("monitor")) / "history"
    history_path = history_dir / "prompt_history"
    assert session.read_user_input() == "hello"
    assert session.read_user_input() == "hello"
    assert len(created_sessions) == 1
    assert isinstance(prompt_calls["history"], FileHistory)
    assert Path(prompt_calls["history"].filename) == history_path
    assert prompt_calls["args"] == ("> ",)
    assert prompt_calls["kwargs"] == {}


def test_read_user_input_uses_in_memory_prompt_session_when_history_path_is_empty(
    monkeypatch,
) -> None:
    """Verify empty history path creates a prompt session without FileHistory."""

    session = build_session()
    prompt_calls = {}
    created_sessions = []

    monkeypatch.setattr(
        "monitor_oop.core.config_service.ConfigService.get_history_file_path",
        lambda self: "",
    )

    class MockPromptSession:
        def __init__(self, *, history=None) -> None:
            prompt_calls["history"] = history
            created_sessions.append(self)

        def prompt(self, *args, **kwargs) -> str:
            prompt_calls["args"] = args
            prompt_calls["kwargs"] = kwargs
            return "hello"

    monkeypatch.setattr(
        "monitor_oop.core.conversation_session.PromptSession",
        MockPromptSession,
    )

    assert session.read_user_input() == "hello"
    assert session.read_user_input() == "hello"
    assert len(created_sessions) == 1
    assert prompt_calls["history"] is None
    assert prompt_calls["args"] == ("> ",)
    assert prompt_calls["kwargs"] == {}


def test_read_user_input_creates_prompt_history_under_configured_history_directory(
    monkeypatch,
) -> None:
    """Verify prompt history is created under the configured history directory."""

    session = build_session()
    prompt_calls = {}
    created_sessions = []

    history_dir = Path(appdirs.user_config_dir("monitor")) / "history"
    history_path = history_dir / "prompt_history"
    monkeypatch.setattr(
        "monitor_oop.core.config_service.ConfigService.get_history_file_path",
        lambda self: str(history_path),
    )

    class MockPromptSession:
        def __init__(self, *, history) -> None:
            prompt_calls["history"] = history
            created_sessions.append(self)

        def prompt(self, *args, **kwargs) -> str:
            prompt_calls["args"] = args
            prompt_calls["kwargs"] = kwargs
            return "hello"

    monkeypatch.setattr(
        "monitor_oop.core.conversation_session.PromptSession",
        MockPromptSession,
    )

    assert session.read_user_input() == "hello"
    assert session.read_user_input() == "hello"
    assert len(created_sessions) == 1
    assert isinstance(prompt_calls["history"], FileHistory)
    assert Path(prompt_calls["history"].filename) == history_path
    assert prompt_calls["args"] == ("> ",)
    assert prompt_calls["kwargs"] == {}


def test_conversation_session_process_non_exit_input_appends_history_and_prints_model_response(
    capsys,
    monkeypatch,
) -> None:
    """Verify non-exit input is recorded and prints the model response."""

    session = build_session()
    session.start()

    response_text = "mocked model response"

    monkeypatch.setattr(
        session.context.llm_service,
        "complete",
        lambda *args, **kwargs: response_text,
    )

    assert session.process_user_input("hello") is True
    assert session.is_running is True
    assert session.context.state.running is True
    history_snapshot = session.context.history_service.snapshot()
    assert any(
        entry == response_text or getattr(entry, "content", None) == response_text
        for entry in history_snapshot
    )

    captured = capsys.readouterr()
    assert response_text in captured.out


def test_conversation_session_process_exit_command() -> None:
    """Verify exit commands stop the session."""

    session = build_session()
    session.start()

    assert session.process_user_input(":exit") is False
    assert session.is_running is False
    assert session.context.state.running is False
