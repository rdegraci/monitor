# Adding an LLM-Callable Tool

This guide reflects the current tool registration structure in the repository.

## Primary files

Current tool registration spans these files:
- `src/monitor/lib/tool_definitions.py`
- `src/monitor/lib/tool_loading.py`
- `src/monitor/lib/tool_profiles.py`
- `src/monitor/core/tools.py`
- `src/monitor/core/tooling.py`

## Current architecture

### Callable registry
`src/monitor/lib/tool_definitions.py` defines `AVAILABLE_TOOLS`, the runtime mapping from tool name to Python callable.

### Tool descriptions
The same module also defines:
- `TOOL_DESCRIPTIONS`
- `GEMINI_TOOL_DESCRIPTIONS`
- `TOOL_STATE`

### Provider/model configuration
`src/monitor/core/tools.py` decides which tool descriptions should be active for the current provider/model configuration.

### Execution
`src/monitor/core/tooling.py` parses tool args and executes tools from `AVAILABLE_TOOLS`.

## Step 1: implement the Python callable

Place the callable in an appropriate module.

Many tool callables currently live in `monitor.lib`, though some registrations point to core or adjacent modules.

Example:

```python
def add(a: int, b: int) -> int:
    return int(a) + int(b)
```

For statically defined tools, most current entries are wired directly into the literal `AVAILABLE_TOOLS` dictionary.

For helper-driven or conditional tool families, the codebase also uses registration helpers in `src/monitor/lib/tool_loading.py` such as `add_tool(...)`. In those paths, make sure both the description catalogs and the runtime callable registry stay in sync.

## Step 2: add the callable to `AVAILABLE_TOOLS`

In `src/monitor/lib/tool_definitions.py`, register the callable:

```python
AVAILABLE_TOOLS["add"] = add
```

In practice, most existing tools are added directly in the literal `AVAILABLE_TOOLS` dictionary.

## Step 3: add a tool description

Add an OpenAI-style tool description to `TOOL_DESCRIPTIONS`.

Example shape:

```python
{
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers.",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    },
}
```

If Gemini-specific descriptions matter, also add the corresponding entry to `GEMINI_TOOL_DESCRIPTIONS`.

## Step 4: decide whether the tool should always exist or be configured conditionally

Some tools are defined statically in `tool_definitions.py`.

Others are conditionally added or removed through helpers in `src/monitor/lib/tool_loading.py` and `src/monitor/core/tools.py`.

Examples of conditional tool families in the current codebase:
- weather tools
- memory tools
- DB tools
- modeling tools
- provider-neutral deterministic edit tools
- Anthropic-native editor tools
- OpenAI editor tools

If your tool belongs to a conditional family, add helper registration logic in `tool_loading.py` and make sure `configure_tools()` in `core/tools.py` enables it under the correct conditions.

## Step 5: assign the tool to a profile group

Registration in `AVAILABLE_TOOLS` / `TOOL_DESCRIPTIONS` alone does not advertise the tool to the model. Advertised tools are filtered by `src/monitor/lib/tool_profiles.py`.

Add the tool name to the appropriate entry in `TOOL_GROUPS`, then confirm which profiles include that group via `PROFILE_GROUPS`. Static profiles today are:
- `minimal`
- `coding` (default)
- `review`
- `full`

Ungrouped tools do not appear in the coding or full catalogs. Verify with:

```text
:tools list
:tools catalog
```

## Step 6: understand current provider behavior

`configure_tools()` currently branches by provider prefix:
- `anthropic`
- `openai`
- `gemini`
- `xai`

This is especially important for editing tools because provider-specific edit catalogs differ.

If your new tool is provider-neutral, it can usually be exposed to all providers.

If it depends on a provider-specific protocol or schema, integrate it carefully into the relevant branch.

## Step 7: argument parsing behavior

`src/monitor/core/tooling.py` currently uses `parse_function_args(...)`.

That means tool arguments may arrive as:
- a JSON string that must be parsed
- an already-parsed mapping

Tools should expect validated keyword arguments by the time the actual callable is invoked, but defensive input validation in the tool itself is still recommended.

## Step 8: consider safety behavior

If your tool:
- writes files
- mutates state
- has large outputs
- should be blocked for sub-agents

then it may need to be integrated into the safety rails in `src/monitor/core/tooling.py`.

Examples already handled there include:
- write-guarded tool lists
- delegated write scope enforcement
- tool-call loop detection
- large file token throttling

If the tool is write-capable, review:
- `WRITE_GUARDED_TOOLS`
- `WRITE_TARGET_EXTRACTORS`

## Example of current deterministic edit tools

The repository already includes tool registrations for:
- `text_file_or_directory_view`
- `text_file_create`
- `text_file_str_replace_in_file`
- `text_file_insert_text_at_line`
- `bulk_replace_in_files`
- `modify_source_code`

These provide good examples of:
- callable registration
- description shape
- safety integration
- provider-conditioned exposure

## Testing guidance

For a new tool, add tests that cover:
- successful invocation
- bad argument handling
- failure reporting
- any provider-specific registration behavior
- safety integration, if applicable

Relevant existing test areas include tool execution, deterministic editors, bulk replace, and built-in command registration.

## Related files
- `src/monitor/lib/tool_definitions.py`
- `src/monitor/lib/tool_loading.py`
- `src/monitor/lib/tool_profiles.py`
- `src/monitor/core/tools.py`
- `src/monitor/core/tooling.py`
