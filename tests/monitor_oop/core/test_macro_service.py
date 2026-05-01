"""Tests for the isolated Monitor OOP macro service."""
from monitor_oop.core.config_service import ConfigService
from monitor_oop.core.macro_service import MacroService


def test_macro_service_add_definition_and_expand() -> None:
    """Verify macro definition storage and expansion passthrough."""

    service = MacroService(ConfigService())

    assert service.add_definition("hello=world") is True
    assert service.list_macros() == {"hello": "world"}
    assert service.expand("{{hello}}") == "{{hello}}"


def test_macro_service_rejects_invalid_definition() -> None:
    """Verify invalid macro definitions are rejected."""

    service = MacroService(ConfigService())

    assert service.add_definition("not-a-definition") is False
    assert service.list_macros() == {}
