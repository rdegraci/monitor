import monitor.config as config


def _invoke_yaml_loader(yaml_overrides: dict[str, object]) -> None:
    """Invoke config.configure_globals with a minimal mocked YAML payload.

    Args:
        yaml_overrides: Top-level YAML keys to merge into the mocked config.
    """
    original_load_yaml_config = config.load_yaml_config
    yaml_payload = {
        "MODEL": "openai/gpt-5.4",
        "MODEL_CONTEXT_WINDOW": 128_000,
        "MODEL_OUTPUT_WINDOW": 8_192,
        **yaml_overrides,
    }

    try:
        config.load_yaml_config = lambda file_path=None: yaml_payload
        config.configure_globals()
    finally:
        config.load_yaml_config = original_load_yaml_config


def test_configure_globals_loads_commit_reasoning_overrides() -> None:
    """Verify commit-specific reasoning settings are loaded into module globals.

    The commit flow reads these values from monitor.config module globals, so
    configure_globals must declare and populate the COMMIT_* names as globals.
    """
    _invoke_yaml_loader(
        {
            "COMMIT_MODEL": "openai/gpt-5.4",
            "COMMIT_REASONING_EFFORT": "high",
            "COMMIT_REASONING_MAX_COMPLETION_TOKENS": 8_000,
        }
    )

    assert config.COMMIT_MODEL == "openai/gpt-5.4"
    assert config.COMMIT_REASONING_EFFORT == "high"
    assert config.COMMIT_REASONING_MAX_COMPLETION_TOKENS == 8_000
