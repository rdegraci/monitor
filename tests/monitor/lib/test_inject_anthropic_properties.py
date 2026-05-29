"""Tests for inject_anthropic_properties — particularly the native-tool
flattening that Anthropic's API requires."""

from monitor.lib.tool_loading import inject_anthropic_properties


def _function_tool(name="foo"):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "a function tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _native_nested(tool_type, name):
    """Native Anthropic tool in the LiteLLM-nested shape that add_tool produces."""
    return {
        "type": tool_type,
        "function": {
            "name": name,
            "description": "Anthropic-defined text editor tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_function_tools_unchanged_except_last_gets_cache_control():
    tools = [_function_tool("a"), _function_tool("b")]
    out = inject_anthropic_properties(tools)
    assert out[0] == tools[0]  # untouched
    assert out[1]["type"] == "function"
    assert out[1]["function"]["name"] == "b"
    assert out[1]["cache_control"] == {"type": "ephemeral"}


def test_native_tool_is_flattened_to_type_and_name():
    """The LiteLLM-nested {type, function: {name, ...}} wrapper must be stripped
    to {type, name} for Anthropic-native protocol tools — Anthropic rejects the
    nested wrapper with 'tools.N.<type>.function: Extra inputs are not permitted'."""
    tools = [_native_nested("text_editor_20250728", "str_replace_based_edit_tool")]
    out = inject_anthropic_properties(tools)
    assert len(out) == 1
    assert "function" not in out[0]
    assert out[0]["type"] == "text_editor_20250728"
    assert out[0]["name"] == "str_replace_based_edit_tool"
    # cache_control still attached to the last entry
    assert out[0]["cache_control"] == {"type": "ephemeral"}


def test_mixed_array_flattens_native_and_preserves_function_tools():
    tools = [
        _function_tool("alpha"),
        _native_nested("text_editor_20250728", "str_replace_based_edit_tool"),
        _function_tool("omega"),
    ]
    out = inject_anthropic_properties(tools)
    # function tool unchanged in shape
    assert out[0]["type"] == "function" and "function" in out[0]
    # native tool flattened
    assert out[1] == {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"}
    # last function tool gets cache_control
    assert out[2]["type"] == "function" and out[2]["function"]["name"] == "omega"
    assert out[2]["cache_control"] == {"type": "ephemeral"}


def test_does_not_mutate_caller_array():
    """The C-1 invariant — module globals (TOOL_DESCRIPTIONS) must not be
    mutated by this transformation, since the same array is reused across
    every API call."""
    tools = [_native_nested("text_editor_20250728", "str_replace_based_edit_tool")]
    snapshot = {"type": tools[0]["type"], "function_keys": set(tools[0]["function"].keys())}
    inject_anthropic_properties(tools)
    assert tools[0]["type"] == snapshot["type"]
    assert set(tools[0]["function"].keys()) == snapshot["function_keys"]
    assert "cache_control" not in tools[0]


def test_malformed_native_entry_passes_through():
    """A native tool missing its name should fall through so the API failure
    is loud and diagnosable, not silently dropped."""
    bad = {"type": "text_editor_20250728", "function": {"description": "x"}}
    out = inject_anthropic_properties([bad])
    assert out[0]["type"] == "text_editor_20250728"
    # cache_control still added (last entry); the malformed tool reaches the
    # API which surfaces the actual error.


def test_empty_or_non_list_input_passes_through():
    assert inject_anthropic_properties([]) == []
    assert inject_anthropic_properties(None) is None
