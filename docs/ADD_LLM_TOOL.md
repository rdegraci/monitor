
# How to Add an LLM-Callable Tool (Function)

This guide explains how to add a new Python function (tool) that the LLM (large language model) can call during a conversation or in response to user prompts.

---

## Step 1: Define Your Function

Write your function in an appropriate module (e.g., `core/tools.py`).
The function typically accepts its arguments as positional or keyword arguments, and should include a docstring.

**Example:**
def add(a: int, b: int) -> int:
    """Add two numbers and return the result."""
    return a + b

---

## Step 2: Create a Tool Mapping for Registration

Describe and map your function in a way the LLM tooling system understands (this is often a dictionary containing the name, description, parameter schema, and a reference to your function).

**Example:**
add_tool = {
    "name": "add",
    "description": "Add two numbers and return the sum.",
    "parameters": {
        "a": {"type": "integer", "description": "The first number."},
        "b": {"type": "integer", "description": "The second number."}
    },
    "function": add
}

---

### Supplementary Note

In this project, tool mappings are usually registered not only by appending manually, but by using helper functions or through bulk-enlisting lists like `TOOL_DESCRIPTIONS`, often found in `lib/tool_definitions.py` or added via utility registration functions.

Contributors should check existing registration patterns (e.g., `add_weather_tools` or similar) to ensure their tool is properly listed and loaded at startup.

It is recommended to consult `lib/tool_definitions.py` and `core/tools.py` for additional context and examples on tool registration and aggregation.

---

## Step 3: Register Your Tool

Add your tool mapping to the tools registry (usually found in `core/tooling.py` or a similar module). This makes your tool visible to the LLM and backend orchestration.

**Example:**
# In core/tooling.py
from monitor.core.tools import add_tool

tools_registry.append(add_tool)
# or use register_tool(add_tool)

---

## Step 4: Ensure Tool Registration at Startup

Make sure your registration logic is called at application startup—usually in the main script or initialization routine.

---

## Step 5: Test the Tool

Run your app and prompt the LLM with an instruction that should use your tool, e.g., "Add 3 and 5". The LLM should route the request to your registered function.

---

## Tips
- Carefully describe parameters; the clearer the schema the easier for the LLM to use your tool.
- Make sure the function is safe: validate inputs if user-generated instructions might be used.
- Review how existing tools are created for advanced patterns (multi-step tools, async handlers, etc).

---

## Quick Reference Table

| Step | Action                                                  |
|------|---------------------------------------------------------|
| 1    | Implement your function                                 |
| 2    | Create and describe a tool mapping                      |
| 3    | Register the mapping in the LLM/tool registry           |
| 4    | Ensure registration occurs at startup                   |
| 5    | Test the function with a suitable LLM prompt            |

---

Now your LLM can call your custom Python tool in responses and workflows!


