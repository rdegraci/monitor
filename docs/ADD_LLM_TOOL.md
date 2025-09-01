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
  - src/monitor/lib/tool_definitions.py contains TOOL_DESCRIPTIONS (static descriptions)
  - src/monitor/lib/tool_loading.py exposes add_tool(...) and the AVAILABLE_TOOLS mapping and helpers (parse_function_args, conversions)
- Runtime tooling orchestration:
  - src/monitor/core/tooling.py exposes configure_tools() which wires tools into the runtime
  - src/monitor/config.py calls configure_tools() during startup

---

## Recommended approach (use add_tool)

Prefer calling add_tool(...) from src/monitor/lib/tool_loading.py to register a tool. add_tool takes care of wiring the function into the runtime AVAILABLE_TOOLS mapping and converting/validating the description schema that the LLM tooling layer expects.

Why use add_tool:
- Centralized validation and normalization of tool descriptions.
- Ensures AVAILABLE_TOOLS contains the callable referenced by tooling code.
- Keeps TOOL_DESCRIPTIONS consistent with the runtime mapping and with model-specific function description helpers.

AVAILABLE_TOOLS
- A dict-like mapping maintained in src/monitor/lib/tool_loading.py.
- Keys are tool names (string), values are the Python callable or a small wrapper object used by tooling code.
- Unit tests commonly patch AVAILABLE_TOOLS to stub or inject tools.

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
# TOOL_DESCRIPTIONS is a list/dict used for bulk registration or static reference.
# Each entry describes the tool's name, description and parameters (JSON-schema-like).
TOOL_DESCRIPTIONS = [
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
```

File: src/monitor/lib/tool_loading.py
```
from typing import Callable, Dict, Any
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS

# AVAILABLE_TOOLS is the runtime mapping of name -> callable
AVAILABLE_TOOLS: Dict[str, Callable[..., Any]] = {}

def add_tool(description: dict, func: Callable[..., Any]) -> None:
    """
    Register a tool with the runtime AVAILABLE_TOOLS and ensure description is present.
    - description: dict containing name/description/parameters (JSON-schema style)
    - func: the Python callable to invoke
    """
    name = description["name"]
    # Basic validation/normalization occurs here (expand as needed)
    AVAILABLE_TOOLS[name] = func
    # Ensure TOOL_DESCRIPTIONS contains this entry (idempotent append/replace)
    # Implementation details depend on how TOOL_DESCRIPTIONS is stored; keep it up-to-date.
    # (actual repo code will update TOOL_DESCRIPTIONS or an equivalent registry)
```

Registration (example wiring):
```
from monitor.core.tools import add
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS
from monitor.lib.tool_loading import add_tool

# If TOOL_DESCRIPTIONS already has the 'add' entry (as above), locate and register it:
for desc in TOOL_DESCRIPTIONS:
    if desc["name"] == "add":
        add_tool(desc, add)
        break
```

This pattern ensures:
- The callable is available at runtime via AVAILABLE_TOOLS["add"].
- The metadata (parameters/schema) is available to convert to model-specific function descriptions.

---

## Manual alternative: editing TOOL_DESCRIPTIONS and AVAILABLE_TOOLS

You can also manually add entries in both places. Example:

- Edit src/monitor/lib/tool_definitions.py to include the description (see TOOL_DESCRIPTIONS example above).
- Edit src/monitor/lib/tool_loading.py (or some startup module) to add the callable:

```
from monitor.core.tools import add as add_func
from monitor.lib.tool_loading import AVAILABLE_TOOLS

AVAILABLE_TOOLS["add"] = add_func
```

This works but bypasses add_tool validation; using add_tool(...) is recommended.

---

## How functions are invoked by the LLM tooling

- The LLM tooling layer invokes functions by name using keyword arguments (the common pattern).
  - Example call: AVAILABLE_TOOLS["add"](a=3, b=5)
- Some LLM responses pass a single JSON string as the argument payload. The runtime helper parse_function_args(...) converts JSON strings to Python dicts and normalizes arguments.
  - parse_function_args sits in src/monitor/lib/tool_loading.py (or is exported from there).
  - Behavior:
    - If the LLM provides a JSON string, parse into dict.
    - If the LLM provides an already-parsed mapping, pass through.
    - The final call always invokes the callable with keyword args: func(**kwargs).

Example invocation flow inside tooling:
```
from monitor.lib.tool_loading import AVAILABLE_TOOLS, parse_function_args

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

Common helpers (see src/monitor/lib/tool_loading.py):
- to_openai_function_descriptions(...) — converts descriptions to OpenAI's functions payload format.
- to_gemini_function_descriptions(...) — converts to Gemini's function schema.
- to_anthropic_function_descriptions(...) — converts to Anthropic's function schema.

Use these helpers when you need to supply the model-specific "functions" or "tools" field to the model API. The add_tool flow will typically ensure descriptions are available in a generic format and conversion is done as needed by the caller that integrates with the model.

Example usage:
```
from monitor.lib.tool_loading import to_openai_function_descriptions, get_tool_descriptions

functions_payload = to_openai_function_descriptions(get_tool_descriptions())
# Pass functions_payload into the OpenAI API call under `functions=...`
```

Check the exact helper names and signatures in src/monitor/lib/tool_loading.py; the helpers centralize differences between provider schemas.

---

## Startup registration: configure_tools() and config.py

- src/monitor/core/tooling.py exposes configure_tools() (or similarly named function) that:
  - Loads TOOL_DESCRIPTIONS
  - Calls add_tool(...) for each entry, wiring AVAILABLE_TOOLS and any required conversion caches
- src/monitor/config.py calls configure_tools() during application startup so tools are available before requests arrive.

Therefore, to ensure your tool is loaded at startup:
- Add your description to TOOL_DESCRIPTIONS (or have an add_tool call in a module which will be imported by configure_tools).
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

- Unit tests should patch/monkeypatch AVAILABLE_TOOLS in src/monitor/lib/tool_loading.py to inject stubs or fake implementations.
- For tests that exercise conversion helpers, use a small TOOL_DESCRIPTIONS snippet and validate the model-specific payloads.
- Example pytest fixture:
```
import pytest
from monitor.lib import tool_loading

@pytest.fixture
def patch_available_tools(monkeypatch):
    fake = {}
    monkeypatch.setattr(tool_loading, "AVAILABLE_TOOLS", fake)
    return fake
```
- Test parse_function_args with both dict inputs and JSON string inputs.

---

## Examples: add_tool vs manual editing

1) Using add_tool (recommended)
```
from monitor.core.tools import add
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS
from monitor.lib.tool_loading import add_tool

# Locate description and register
desc = next(d for d in TOOL_DESCRIPTIONS if d["name"] == "add")
add_tool(desc, add)
```

2) Manually editing (less safe)
- Add the description to TOOL_DESCRIPTIONS (src/monitor/lib/tool_definitions.py).
- Ensure AVAILABLE_TOOLS["add"] = add is executed before tooling is used (e.g., in configure_tools or an import-time registration).

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
| 2    | Add a TOOL_DESCRIPTIONS entry in src/monitor/lib/tool_definitions.py |
| 3    | Register the mapping at runtime using add_tool(...) from src/monitor/lib/tool_loading.py (or ensure configure_tools() runs) |
| 4    | Ensure configure_tools() is invoked at startup from src/monitor/config.py |
| 5    | Test by patching AVAILABLE_TOOLS in unit tests and by invoking via the tooling integration |

---

Now your LLM can call your custom Python tool in responses and workflows using the repository's recommended registration and invocation patterns.
