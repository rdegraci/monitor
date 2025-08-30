# How to Add a New Built-In Command

This guide explains how to add a new built-in command to the application, enabling you to extend the interactive CLI with custom functionality. It reflects the current codebase behavior and registration patterns.

---

## Overview / Key concepts

- Handler location vs registration:
  - Implement the command handler in an appropriate module (for example, `monitor/lib/built_in_commands.py` for library-style commands or a `core` module for tightly-coupled core commands).
  - Register the handler in `monitor/core/built_ins.py` by adding an entry in `configure_built_ins()` — that file is the registration surface (it organizes command groups and calls the registration helper).

- Calling contract (important):
  - The built-in executor calls your handler with a *single string argument* that contains everything typed by the user after the command name.
  - Prefer the signature `def my_command(arg=None):` and accept the argument as a string (it may be empty or None).

- Return values vs printing:
  - The built-in executor (`execute_built_in_function` in `monitor/lib/built_ins_utils.py`) invokes your function but does not capture and print its return value. Therefore, your handler should typically print its output directly.
  - If you prefer to return values, register a wrapper that prints the returned value.

- Automatic adapters and explicit adapters:
  - `monitor/core/built_ins.py` contains `_make_callable(func)` which adapts 0- or 1-argument functions to the single-argument calling interface.
  - If a function requires more than one positional parameter, you must register an explicit adapter lambda in `configure_built_ins()` that transforms the single string argument into the parameters the function needs.

- Registration API:
  - The low-level helper that stores registrations is `append_function_to_built_ins(new_dict)` in `monitor/lib/built_ins_utils.py`.
  - `configure_built_ins()` adds a `group_description` to each mapping before calling the append helper.

- Colon (`:`) prefix:
  - Using `:` (e.g., `:llm`) is a common convention in built-ins to avoid name collisions, but it is not enforced. The command matching logic compares the first word to the registered `command` string, so consistency is what matters.

---

## Step 1: Define your command handler

Place the implementation in an appropriate module. Example in `monitor/lib/built_in_commands.py`:

```python
def echo_command(arg=None):
    """Echo the provided arguments back to the user."""
    if arg:
        print(arg)
    else:
        print("Nothing to echo.")
```

Notes:
- `arg` receives the remainder of the CLI command as a single string (e.g., if the user types `:echo Hello World`, `arg == "Hello World"`).
- Use defensive input parsing and error handling inside the handler.

---

## Step 2: Register the command in `configure_built_ins()`

In `monitor/core/built_ins.py`, locate `configure_built_ins()`. Commands are organized into groups and each command is registered by adding a mapping with keys like `"command"`, `"function"`, and `"description"`.

Direct registration example (recommended for simple handlers using arg=None):

```python
{
    "command": ":echo",
    "function": echo_command,
    "description": "Echo user-supplied text (usage: :echo your text)",
}
```

Notes:
- `configure_built_ins()` often calls `_make_callable(handler)` automatically for you when building entries, which adapts handlers that accept no argument or a single argument.
- The call site will enrich each mapping with `"group_description"` before calling `append_function_to_built_ins()`.

Adapter registration example (for handlers that need additional dependencies or more parameters):

Suppose you have a function:

```python
def complex_handler(session, mode):
    # requires two parameters
    ...
```

Register via a lambda adapter that parses the single incoming string and injects dependencies:

```python
{
    "command": ":complex",
    "function": lambda arg=None: complex_handler(session_from_context(), parse_mode(arg)),
    "description": "Run a complex handler that needs session and mode",
}
```

Or if a handler needs multiple parsed values from `arg`, the lambda should parse `arg` and call the underlying function accordingly.

Examples in the codebase:
- `configure_built_ins()` uses `_make_callable(func)` for many handlers and explicit `lambda arg=None: ...` adapters for cases that need extra context (for example, adapters that inject TOOL_DESCRIPTIONS, config, logger, etc.).

---

## Step 3: (Re)Start the application

Restart the app so it loads the updated built-in command registry. `configure_built_ins()` runs at startup to register all built-ins.

---

## Step 4: Use the command

At the CLI prompt, type:

```
:echo Hello World!
```

With the example `echo_command` above this prints:

```
Hello World!
```

---

## Returning Values From Built-In Commands (corrected)

- `execute_built_in_function` calls `function_to_run(arguments)` but does not examine or print its return value.
- Best practice:
  - Have your handler print outputs directly (recommended).
  - Or, register a wrapper that calls the handler, captures the returned value, and prints it:

```python
def wrapper(arg=None):
    result = maybe_returning_handler(arg)
    if result is not None:
        print(result)
```

---

## Error Handling Best Practices (practical)

- Use try/except in your handlers to provide helpful feedback.
- Validate and sanitize `arg`.
- If a function requires more than one positional parameter, prefer making the dependency explicit with a lambda adapter at registration time; this avoids implicit runtime errors and documents the need for those parameters.
- Registration-time safety: `configure_built_ins()` uses a helper that logs registration errors; if `append_function_to_built_ins()` raises, the registration helper reports it without crashing the entire startup.

---

## Examples (accurate with current codebase)

Simple echo (implementation and registration):

Implementation (e.g., `monitor/lib/built_in_commands.py`):

```python
def echo_command(arg=None):
    """Echo text provided by the user."""
    if arg:
        print(arg)
    else:
        print("Nothing to echo.")
```

Registration in `configure_built_ins()` (in `monitor/core/built_ins.py`):

```python
{
    "command": ":echo",
    "function": echo_command,  # configure_built_ins or _make_callable will adapt as needed
    "description": "Echo user text",
}
```

Handler that returns instead of printing, with wrapper to print:

```python
def double_command(arg=None):
    try:
        return float(arg) * 2
    except Exception:
        return "Please enter a valid number."

# Wrapper used when registering:
{
    "command": ":double",
    "function": lambda arg=None: print(double_command(arg)),
    "description": "Double a number (usage: :double 5)",
}
```

Handler needing multiple dependencies — use adapter:

```python
def run_query_with_client(client, query_str):
    return client.query(query_str)

# Registration with adapter that extracts client and passes parsed arg:
{
    "command": ":qclient",
    "function": lambda arg=None: print(run_query_with_client(get_client(), arg)),
    "description": "Run query using a specific client",
}
```

---

## Quick Reference Table

| Step | Action |
|------|--------|
| 1 | Implement handler in a module (prefer `monitor/lib/built_in_commands.py` for library commands). |
| 2 | Register it in `configure_built_ins()` with keys `command`, `function`, `description`. |
| 3 | If your handler prints behavior directly, prefer `def fn(arg=None)`. |
| 4 | If your handler needs additional parameters or dependencies, register a lambda adapter. |
| 5 | Restart the app and use the command at the CLI. |

---

## Where to look in the code

- Registration and adapter code: `src/monitor/core/built_ins.py` (`configure_built_ins()`, `_make_callable`, `_safe_register`).
- Registry and execution: `src/monitor/lib/built_ins_utils.py` (`append_function_to_built_ins()`, `execute_built_in_function()`).
- Examples of handlers: `src/monitor/lib/built_in_commands.py`.

