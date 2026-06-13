"""Tests for TOOL_OUTPUT_TOKEN_LIMIT config loading and adapter fallback."""

import logging

from monitor import config


def test_default_tool_output_token_limit_is_32768() -> None:
    """Verify the module default matches the intended per-tool output cap.

    The default is 32K (see config.TOOL_OUTPUT_TOKEN_LIMIT and the matching
    config.yaml.example key) — a per-tool blast-radius guard, intentionally much
    smaller than the model context window.
    """
    assert config.TOOL_OUTPUT_TOKEN_LIMIT == 32_768


def test_yaml_loader_accepts_valid_tool_output_token_limit() -> None:
    """Verify YAML can raise or lower the per-tool output token limit."""
    original = config.TOOL_OUTPUT_TOKEN_LIMIT
    try:
        _invoke_yaml_loader({"TOOL_OUTPUT_TOKEN_LIMIT": 12_345})
        assert config.TOOL_OUTPUT_TOKEN_LIMIT == 12_345
    finally:
        config.TOOL_OUTPUT_TOKEN_LIMIT = original


def test_yaml_loader_rejects_negative_tool_output_token_limit(caplog) -> None:
    """Verify negative YAML values are rejected and the default is preserved."""
    original = config.TOOL_OUTPUT_TOKEN_LIMIT
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"TOOL_OUTPUT_TOKEN_LIMIT": -1})
        assert config.TOOL_OUTPUT_TOKEN_LIMIT == original
        assert any("must be >= 0" in record.getMessage() for record in caplog.records)
    finally:
        config.TOOL_OUTPUT_TOKEN_LIMIT = original


def test_yaml_loader_rejects_non_integer_tool_output_token_limit(caplog) -> None:
    """Verify non-integer YAML values are rejected and the default is preserved."""
    original = config.TOOL_OUTPUT_TOKEN_LIMIT
    try:
        caplog.set_level(logging.WARNING, logger="monitor.config")
        _invoke_yaml_loader({"TOOL_OUTPUT_TOKEN_LIMIT": "many"})
        assert config.TOOL_OUTPUT_TOKEN_LIMIT == original
        assert any("is not an integer" in record.getMessage() for record in caplog.records)
    finally:
        config.TOOL_OUTPUT_TOKEN_LIMIT = original


def _invoke_yaml_loader(yaml_overrides: dict[str, object]) -> None:
    """Invoke config.configure_globals() with a minimal mocked YAML payload.

    Args:
        yaml_overrides: Top-level YAML keys to merge into the mocked config.
    """
    original_load_yaml_config = config.load_yaml_config

    yaml_payload = {
        "MODEL": "openai/gpt-5.4-mini",
        "MODEL_CONTEXT_WINDOW": 400_000,
        "MODEL_OUTPUT_WINDOW": 8_192,
        **yaml_overrides,
    }

    try:
        config.load_yaml_config = lambda file_path=None: yaml_payload
        config.configure_globals()
    finally:
        config.load_yaml_config = original_load_yaml_config
