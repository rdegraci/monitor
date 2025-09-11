# How to Add an LLM-Callable Tool (Function) — Repo-Accurate Guide

This document replaces the older generic guide and describes the exact files, helpers, and registration patterns used in this repository:

- src/monitor/lib/tool_definitions.py
- src/monitor/lib/tool_loading.py
- src/monitor/core/tools.py
- src/monitor/core/tooling.py
- src/monitor/config.py

Goal: show the recommended, minimal, ready-to-paste pattern (using add_tool(...) from monitor/lib/tool_loading.py), explain AVAILABLE_TOOLS, invocation behavior, model-specific conversion helpers, startup registration, rate/token notes, and testing tips.

---

## Quick summary of key pieces (map)

- Implement function (tool) code in:
  - src/monitor/core/tools.py (or another core/ module)
- Describe and register tools:
  - src/monitor/lib/tool_definitions.py contains TOOL_DESCRIPTIONS (static descriptions), GEMINI_TOOL_DESCRIPTIONS, AVAILABLE_TOOLS, and TOOL_STATE
  - src/monitor/lib/tool_loading.py exposes add_tool(...) and the add_*_tools functions and helpers (parse_function_args is not here, but conversions may be)
- Runtime tooling orchestration:
  - src/monitor/core/tooling.py exposes parse_function_args and configure_tools() which wires tools into the runtime
  - src/monitor/config.py calls configure_tools() during startup

---

## Recommended approach (use add_tool)

Prefer calling add_tool(...) from src/monitor/lib/tool_loading.py to register a tool. add_tool takes (tool_descriptions, gemini_tool_descriptions, tool_state, tool_definition) and appends to the respective lists in src/monitor/lib/tool_definitions.py.

Why use add_tool:
- Centralized validation and normalization of tool descriptions.
- Ensures TOOL_DESCRIPTIONS and GEMINI_TOOL_DESCRIPTIONS contain the entries, and TOOL_STATE is updated.
- Keeps the mappings consistent with the runtime and with model-specific function description helpers.

AVAILABLE_TOOLS
- A dict-like mapping maintained in src/monitor/lib/tool_definitions.py.
- Keys are tool names (string), values are the Python callable or a small wrapper object used by tooling code.
- TOOL_STATE tracks active tools.
- Unit tests commonly patch AVAILABLE_TOOLS and TOOL_STATE to stub or inject tools.

---

## Minimal, ready-to-paste example

File: src/monitor/core/tools.py
```
def add(a: int, b: int) -> int:
    """
    Add two integers and return the result.
    Keep this function pure and validate inputs if necessary.
    """
    return int(a) + int(b)
```

File: src/monitor/lib/tool_definitions.py
```
# TOOL_DESCRIPTIONS is a list of tool descriptions in the format expected by the runtime.
# Each entry is a dict: {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
TOOL_DESCRIPTIONS = [
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two integers and return their sum.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "First number"},
                    "b": {"type": "integer", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        }
    }
]

# GEMINI_TOOL_DESCRIPTIONS for Gemini-specific format
GEMINI_TOOL_DESCRIPTIONS = [
    {
        "name": "add",
        "description": "Add two integers and return their sum.",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
    }
]

# AVAILABLE_TOOLS is the runtime mapping of name -> callable
AVAILABLE_TOOLS: Dict[str, Callable[..., Any]] = {}

# TOOL_STATE tracks active tools
TOOL_STATE = {}
```

File: src/monitor/lib/tool_loading.py
```
from typing import Callable, Dict, Any
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, AVAILABLE_TOOLS, TOOL_STATE

def add_tool(tool_descriptions, gemini_tool_descriptions, tool_state, tool_definition):
    """
    Register a tool by appending to tool_descriptions and gemini_tool_descriptions, updating tool_state.
    - tool_descriptions: list to append the general description
    - gemini_tool_descriptions: list to append the Gemini-specific description
    - tool_state: dict to update with tool state
    - tool_definition: dict containing the tool's metadata and callable
    """
    # Append to lists
    tool_descriptions.append(tool_definition["description"])
    gemini_tool_descriptions.append(tool_definition["gemini_description"])
    # Update state
    tool_state[tool_definition["name"]] = "active"
    # Possibly update AVAILABLE_TOOLS if needed
    AVAILABLE_TOOLS[tool_definition["name"]] = tool_definition["callable"]
```

Registration (example wiring):
```
from monitor.core.tools import add
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, AVAILABLE_TOOLS, TOOL_STATE
from monitor.lib.tool_loading import add_tool

# Prepare the tool definition
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
                    "b": {"type": "integer", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        }
    },
    "gemini_description": {
        "name": "add",
        "description": "Add two integers and return their sum.",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
    },
    "callable": add
}

add_tool(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE, tool_def)
```

This pattern ensures:
- The descriptions are added to the lists.
- TOOL_STATE is updated.
- AVAILABLE_TOOLS contains the callable.

---

## Manual alternative: editing TOOL_DESCRIPTIONS and AVAILABLE_TOOLS

You can also manually add entries in both places. Example:

- Edit src/monitor/lib/tool_definitions.py to include the description in TOOL_DESCRIPTIONS and GEMINI_TOOL_DESCRIPTIONS, and add to AVAILABLE_TOOLS and TOOL_STATE.

```
from monitor.core.tools import add as add_func
from monitor.lib.tool_definitions import AVAILABLE_TOOLS, TOOL_STATE, TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS

AVAILABLE_TOOLS["add"] = add_func
TOOL_STATE["add"] = "active"
TOOL_DESCRIPTIONS.append({
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers and return their sum.",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
    }
})
GEMINI_TOOL_DESCRIPTIONS.append({
    "name": "add",
    "description": "Add two integers and return their sum.",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "integer", "description": "First number"},
            "b": {"type": "integer", "description": "Second number"}
        },
        "required": ["a", "b"]
    }
})
```

This works but bypasses add_tool validation; using add_tool(...) is recommended.

---

## How functions are invoked by the LLM tooling

- The LLM tooling layer invokes functions by name using keyword arguments (the common pattern).
  - Example call: AVAILABLE_TOOLS["add"](a=3, b=5)
- Some LLM responses pass a single JSON string as the argument payload. The runtime helper parse_function_args(...) converts JSON strings to Python dicts and normalizes arguments.
  - parse_function_args sits in src/monitor/core/tooling.py.
  - Behavior:
    - If the LLM provides a JSON string, parse into dict.
    - If the LLM provides an already-parsed mapping, pass through.
    - The final call always invokes the callable with keyword args: func(**kwargs).

Example invocation flow inside tooling:
```
from monitor.lib.tool_definitions import AVAILABLE_TOOLS
from monitor.core.tooling import parse_function_args

# model_response contains something like: {"name": "add", "arguments": "{\"a\": 3, \"b\": 5}"}
name = model_response["name"]
raw_args = model_response["arguments"]
kwargs = parse_function_args(raw_args)  # returns a dict { "a": 3, "b": 5 }
result = AVAILABLE_TOOLS[name](**kwargs)
```

Note: parse_function_args also handles minor type coercion and basic validation; for complex validation prefer explicit checks inside the tool function.

---

## GEMINI / Anthropic / OpenAI variants and conversion helpers

Different models expect different function/parameter description formats. This repo provides conversion helpers to translate TOOL_DESCRIPTIONS entries into the target model's required schema.

Common helpers (see src/monitor/lib/tool_loading.py or related modules):
- to_openai_function_descriptions(...) — converts descriptions to OpenAI's functions payload format.
- to_gemini_function_descriptions(...) — uses GEMINI_TOOL_DESCRIPTIONS directly.
- to_anthropic_function_descriptions(...) — converts to Anthropic's function schema.

Use these helpers when you need to supply the model-specific "functions" or "tools" field to the model API. The add_tool flow will typically ensure descriptions are available in a generic format and conversion is done as needed by the caller that integrates with the model.

Example usage:
```
from monitor.lib.tool_loading import to_openai_function_descriptions
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS

functions_payload = to_openai_function_descriptions(TOOL_DESCRIPTIONS)
# Pass functions_payload into the OpenAI API call under `functions=...`
```

Check the exact helper names and signatures in src/monitor/lib/tool_loading.py; the helpers centralize differences between provider schemas.

---

## Startup registration: configure_tools() and config.py

- src/monitor/core/tooling.py exposes configure_tools() (or similarly named function) that:
  - Loads TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS
  - Calls add_*_tools functions from tool_loading.py for each entry, wiring AVAILABLE_TOOLS, TOOL_STATE, and any required conversion caches
- src/monitor/config.py calls configure_tools() during application startup so tools are available before requests arrive.

Therefore, to ensure your tool is loaded at startup:
- Add your description to TOOL_DESCRIPTIONS and GEMINI_TOOL_DESCRIPTIONS (or have an add_tool call in a module which will be imported by configure_tools).
- Ensure configure_tools() runs in src/monitor/config.py initialization (this is the default behavior in the repo).

---

## Rate-limiting, token-counting, and high-token operations

Some tools operate on potentially large inputs and can consume many tokens (cost, latency) or perform expensive IO:
- cat_file
- list_directory_contents
- modify_source_code
- any operation that reads large files, repositories, or binaries

Guidance:
- Rate-limit or throttle high-cost tools at the tool-wrapper level.
- Consider chunking large payloads and streaming results if supported by the model or UI.
- If your tool accepts `max_tokens` or `summary_length` style arguments, enforce safe upper bounds.
- When implementing modify_source_code or other code-writing tools, validate user permissions and create audit logs before making changes.

Token-counting:
- If you compute token usage estimates, do so before calling the model to avoid surprises.
- Prefer pre-filtering or summarization before sending content-heavy inputs to the model.

---

## Testing tips

- Unit tests should patch/monkeypatch AVAILABLE_TOOLS and TOOL_STATE in src/monitor/lib/tool_definitions.py to inject stubs or fake implementations.
- For tests that exercise conversion helpers, use a small TOOL_DESCRIPTIONS snippet and validate the model-specific payloads.
- Example pytest fixture:
```
import pytest
from monitor.lib import tool_definitions

@pytest.fixture
def patch_available_tools(monkeypatch):
    fake = {}
    monkeypatch.setattr(tool_definitions, "AVAILABLE_TOOLS", fake)
    monkeypatch.setattr(tool_definitions, "TOOL_STATE", {})
    return fake
```
- Test parse_function_args with both dict inputs and JSON string inputs.

---

## Examples: add_tool vs manual editing

1) Using add_tool (recommended)
```
from monitor.core.tools import add
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, AVAILABLE_TOOLS, TOOL_STATE
from monitor.lib.tool_loading import add_tool

# Prepare tool definition and register
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
                    "b": {"type": "integer", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        }
    },
    "gemini_description": {
        "name": "add",
        "description": "Add two integers and return their sum.",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
    },
    "callable": add
}
add_tool(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE, tool_def)
```

2) Manually editing (less safe)
- Add the description to TOOL_DESCRIPTIONS and GEMINI_TOOL_DESCRIPTIONS in src/monitor/lib/tool_definitions.py.
- Ensure AVAILABLE_TOOLS["add"] = add and TOOL_STATE["add"] = "active" are executed before tooling is used (e.g., in configure_tools or an import-time registration).

---

## Tips
- Describe parameters clearly in the TOOL_DESCRIPTIONS schema — the clearer the schema the easier the LLM selects and formats calls.
- Validate inputs inside the function to guard against malicious or malformed args.
- Prefer add_tool(...) to keep registration logic centralized.
- For async or multi-step tools, follow existing patterns in core/tools.py for async handlers or background tasks.

---

## Quick Reference Table

| Step | Action                                                  |
|------|---------------------------------------------------------|
| 1    | Implement your function in src/monitor/core/tools.py    |
| 2    | Add TOOL_DESCRIPTIONS and GEMINI_TOOL_DESCRIPTIONS entries in src/monitor/lib/tool_definitions.py |
| 3    | Register the mapping at runtime using add_tool(...) from src/monitor/lib/tool_loading.py (or ensure configure_tools() runs) |
| 4    | Ensure configure_tools() is invoked at startup from src/monitor/config.py |
| 5    | Test by patching AVAILABLE_TOOLS and TOOL_STATE in unit tests and by invoking via the tooling integration |

---

Now your LLM can call your custom Python tool in responses and workflows using the repository's recommended registration and invocation patterns.
