# Repo-Accurate Guide: Adding an LLM-Callable Tool (Concise)

This concise guide shows the canonical pattern used in this repository to register LLM-callable tools (functions). It focuses on the recommended add_tool(...) flow, explicit callable registration in AVAILABLE_TOOLS, model-specific conversion helpers, invocation behavior, testing notes, and a final checklist.

## Key files
- src/monitor/core/tools.py         — implement tool callables here
- src/monitor/lib/tool_definitions.py — TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, AVAILABLE_TOOLS, TOOL_STATE
- src/monitor/lib/tool_loading.py  — add_tool(...), inject_openai_properties(...), inject_anthropic_properties(...)
- src/monitor/core/tooling.py      — parse_function_args(...), configure_tools()
- src/monitor/config.py            — calls configure_tools() at startup

## Principles (brief)
- Use add_tool(...) to register descriptions and update TOOL_STATE. It centralizes validation and normalization.
- add_tool(...) does NOT install the Python callable into AVAILABLE_TOOLS. Install the callable explicitly (AVAILABLE_TOOLS[name] = callable).
- Use inject_openai_properties(...) and inject_anthropic_properties(...) when creating model-specific payloads from TOOL_DESCRIPTIONS.
- parse_function_args(...) converts JSON-string arguments from model responses into dicts and normalizes arguments before calling the callable.

## Canonical example: add_tool + explicit callable registration

Prepare the tool in src/monitor/core/tools.py (example implementation):
    def add(a: int, b: int) -> int:
        """
        Add two integers and return the result.
        Validate inputs inside the function as needed.
        """
        return int(a) + int(b)

Register descriptions and state via add_tool, then explicitly install the callable:
    from monitor.core.tools import add
    from monitor.lib.tool_definitions import (
        TOOL_DESCRIPTIONS,
        GEMINI_TOOL_DESCRIPTIONS,
        AVAILABLE_TOOLS,
        TOOL_STATE,
    )
    from monitor.lib.tool_loading import add_tool

    tool_def = {
        "name": "add",
        "description": {
            "type": "function",
            "function": {
                "name": "add",
                "description": "Add two integers and return their sum.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer", "description": "First number"},
                        "b": {"type": "integer", "description": "Second number"},
                    },
                    "required": ["a", "b"],
                },
            }
        },
        "gemini_description": {
            "name": "add",
            "description": "Add two integers and return their sum.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "First number"},
                    "b": {"type": "integer", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        },
        # Optional convenience pointer. add_tool will NOT install this into AVAILABLE_TOOLS.
        "callable": add,
    }

    ok = add_tool(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE, tool_def)
    if not ok:
        raise RuntimeError("add_tool failed to register 'add'")

    # Explicitly register the callable so the runtime can call it.
    AVAILABLE_TOOLS["add"] = add

Notes:
- Check add_tool's return value and fail fast if registration is invalid.
- Keep callable installation explicit for traceability and testability.

## Invocation flow used by the tooling layer

Typical runtime flow:
    from monitor.lib.tool_definitions import AVAILABLE_TOOLS
    from monitor.core.tooling import parse_function_args

    # model_response example:
    # {"name": "add", "arguments": "{\"a\": 3, \"b\": 5}"}
    name = model_response["name"]
    raw_args = model_response["arguments"]
    kwargs = parse_function_args(raw_args)  # returns dict {"a": 3, "b": 5}
    # Tooling should verify TOOL_STATE[name] if required by runtime policy
    result = AVAILABLE_TOOLS[name](**kwargs)

parse_function_args behavior (summary):
- If input is a JSON string, parse into dict.
- If already a mapping, return as dict.
- Normalize minor types where reasonable (e.g., numeric strings -> numbers) but prefer explicit checks in the tool.

## Model-specific helper usage

Convert TOOL_DESCRIPTIONS into the provider-specific "functions/tools" payloads.

OpenAI example:
    from monitor.lib.tool_loading import inject_openai_properties
    from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS

    openai_functions = inject_openai_properties(TOOL_DESCRIPTIONS)
    # Pass openai_functions into OpenAI SDK as the `functions=` parameter.

Anthropic example:
    from monitor.lib.tool_loading import inject_anthropic_properties
    from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS

    anthropic_tools = inject_anthropic_properties(TOOL_DESCRIPTIONS)
    # Use anthropic_tools as required by Anthropic APIs.

Reminder: confirm the exact signatures of inject_openai_properties and inject_anthropic_properties in src/monitor/lib/tool_loading.py.

## Succinct testing tips

- Unit tests should monkeypatch tool_definitions.AVAILABLE_TOOLS and TOOL_STATE:
    import pytest
    from monitor.lib import tool_definitions
    from monitor.core import tooling

    @pytest.fixture
    def patch_available_tools(monkeypatch):
        fake = {}
        monkeypatch.setattr(tool_definitions, "AVAILABLE_TOOLS", fake)
        monkeypatch.setattr(tool_definitions, "TOOL_STATE", {})
        return fake

    def test_parse_function_args_with_json_string():
        raw = '{"a": 1, "b": 2}'
        parsed = tooling.parse_function_args(raw)
        assert isinstance(parsed, dict)
        assert parsed["a"] == 1 and parsed["b"] == 2

    def test_invocation_flow_with_callable(patch_available_tools):
        def stub_add(a, b):
            return a + b
        patch_available_tools["add"] = stub_add
        tool_definitions.TOOL_STATE["add"] = "active"
        model_response = {"name": "add", "arguments": '{"a": 3, "b": 5}'}
        kwargs = tooling.parse_function_args(model_response["arguments"])
        result = patch_available_tools[model_response["name"]](**kwargs)
        assert result == 8

- For IO operations, use tmp_path and isolate side-effects.
- For network calls, prefer responses/requests-mock/respx rather than patching internals.
- Test both JSON-encoded argument strings and already-parsed dicts.
- Assert TOOL_STATE behavior when your runtime depends on it.
- Restore global state in teardown or rely on monkeypatch fixtures.

## Small security & reliability reminders
- Validate inputs inside the tool function for safety.
- Rate-limit or throttle heavy tools and enforce max_tokens / max_bytes where appropriate.
- Log/audit any tool that mutates state or sensitive data.
- For modify operations, require permission checks and create a backup or audit trail.

## Final concise checklist
- [ ] Implement the Python callable in src/monitor/core/tools.py.
- [ ] Use add_tool(...) to register descriptions and update TOOL_STATE; check its return value.
- [ ] Explicitly set AVAILABLE_TOOLS["your_tool_name"] = your_callable.
- [ ] Use inject_openai_properties(...) / inject_anthropic_properties(...) when building model payloads.
- [ ] Ensure configure_tools() runs at startup (src/monitor/config.py).
- [ ] Add unit tests that monkeypatch AVAILABLE_TOOLS and TOOL_STATE and test parse_function_args behavior.
- [ ] Add audit logging and input validation for mutating or high-cost tools.

End of concise guide.
