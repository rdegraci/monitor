"""Tests for Ollama config load and derived runtime windows."""

import importlib

import monitor.config as config
from monitor.lib.llm_model_utils import resolve_turn_model


def _invoke_yaml_loader(yaml_overrides: dict[str, object]) -> None:
    """Invoke config.configure_globals() with a mocked YAML payload.

    Args:
        yaml_overrides: Top-level YAML keys to merge into the mocked config.
    """
    original_load_yaml_config = config.load_yaml_config
    yaml_payload = {
        "MODEL": "OLLAMA",
        "OLLAMA": {
            "MODEL": "llama3.1",
            "BASE_URL": "http://127.0.0.1:11434",
            "CONTEXT_WINDOW": 128_000,
            "OUTPUT_WINDOW": 8_192,
        },
        **yaml_overrides,
    }
    try:
        config.load_yaml_config = lambda file_path=None: yaml_payload
        config.configure_globals()
    finally:
        config.load_yaml_config = original_load_yaml_config


def test_ollama_config_derives_runtime_windows() -> None:
    """Verify Ollama YAML populates the derived runtime globals."""
    _invoke_yaml_loader({})
    assert config.MODEL == "ollama/llama3.1"
    assert config.MODEL_CONTEXT_WINDOW == 128_000
    assert config.MODEL_OUTPUT_WINDOW == 8_192
    assert config.MODEL_INPUT_WINDOW == 119_808
    assert config.MAX_TOKEN_COUNT == 128_000
    assert config.OLLAMA_BASE_URL == "http://127.0.0.1:11434"


def test_ollama_steady_model_allows_adv_reasoning_swap() -> None:
    """Verify Ollama steady-provider turns can swap to a reasoning provider."""
    resolved = resolve_turn_model(
        "OLLAMA",
        "openai/gpt-5.4",
        True,
        "openai/gpt-5",
        steady_provider="ollama",
    )
    assert resolved == "openai/gpt-5.4"


def test_non_ollama_configs_keep_existing_windows() -> None:
    """Verify legacy non-Ollama shape still behaves as before."""
    original_load_yaml_config = config.load_yaml_config
    try:
        config.load_yaml_config = lambda file_path=None: {
            "MODEL": "openai/gpt-5.4",
            "MODEL_CONTEXT_WINDOW": 128_000,
            "MODEL_OUTPUT_WINDOW": 8_192,
        }
        config.configure_globals()
        assert config.MODEL == "openai/gpt-5.4"
        assert config.MODEL_CONTEXT_WINDOW == 128_000
        assert config.MODEL_OUTPUT_WINDOW == 8_192
    finally:
        config.load_yaml_config = original_load_yaml_config
