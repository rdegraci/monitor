"""Tests for the isolated Monitor OOP macro service."""
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.macro_service import MacroService


class FakeMacroStore:
    def __init__(self, loaded_macros: dict[str, str] | None = None) -> None:
        self.loaded_macros = loaded_macros
        self.saved_payloads: list[dict[str, str]] = []

    def load(self) -> dict[str, str] | None:
        return self.loaded_macros

    def save(self, payload: dict[str, str]) -> None:
        self.saved_payloads.append(payload.copy())


class FakeMacroExpander:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def expand(self, text: str, macros: dict[str, str]) -> str:
        self.calls.append((text, macros.copy()))
        if text == "{{greeting}}":
            return "world"
        return text.replace("{{hello}}", macros["hello"]).replace("{{greeting}}", macros["greeting"])


def test_macro_service_loads_empty_or_missing_macros() -> None:
    """Verify empty and missing macro stores load deterministically."""

    empty_store = FakeMacroStore(loaded_macros={})
    service = MacroService(ConfigService(), store=empty_store, expander=FakeMacroExpander())

    service.reload()
    assert service.list_macros() == {}

    missing_store = FakeMacroStore(loaded_macros=None)
    service = MacroService(ConfigService(), store=missing_store, expander=FakeMacroExpander())

    service.reload()
    assert service.list_macros() == {}


def test_macro_service_add_definition_persists_via_store() -> None:
    """Verify macro definition storage is persisted through the store."""

    store = FakeMacroStore()
    service = MacroService(ConfigService(), store=store, expander=FakeMacroExpander())

    assert service.add_definition("hello=world") is True
    assert service.list_macros() == {"hello": "world"}
    assert store.saved_payloads == [{"hello": "world"}]


def test_macro_service_list_macros_returns_copy() -> None:
    """Verify callers cannot mutate internal macro state via list_macros."""

    service = MacroService(ConfigService(), store=FakeMacroStore(), expander=FakeMacroExpander())
    assert service.add_definition("hello=world") is True

    macros = service.list_macros()
    macros["hello"] = "mutated"

    assert service.list_macros() == {"hello": "world"}


def test_macro_service_recursive_expansion_through_expander() -> None:
    """Verify recursive expansion is delegated through MacroExpander."""

    expander = FakeMacroExpander()
    service = MacroService(ConfigService(), store=FakeMacroStore(), expander=expander)
    assert service.add_definition("hello=world") is True
    assert service.add_definition("greeting={{hello}}") is True

    assert service.expand("{{greeting}}") == "world"
    assert expander.calls == [("{{greeting}}", {"hello": "world", "greeting": "{{hello}}"})]


def test_macro_service_reload_behavior() -> None:
    """Verify reloading refreshes macros from the store."""

    store = FakeMacroStore(loaded_macros={"hello": "world"})
    service = MacroService(ConfigService(), store=store, expander=FakeMacroExpander())

    service.reload()
    assert service.list_macros() == {"hello": "world"}

    store.loaded_macros = {"bye": "moon"}
    service.reload()
    assert service.list_macros() == {"bye": "moon"}


def test_macro_service_rejects_invalid_definition() -> None:
    """Verify invalid macro definitions are rejected without persistence."""

    store = FakeMacroStore()
    service = MacroService(ConfigService(), store=store, expander=FakeMacroExpander())

    assert service.add_definition("invalid-definition") is False
    assert service.list_macros() == {}
    assert store.saved_payloads == []
