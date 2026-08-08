# How to Add a New Built-In Command

This guide reflects the current built-in registration path in the repository.

## Where built-ins are registered

Built-ins are registered in:
- `src/monitor/core/built_ins.py`

The main registration function is:
- `configure_built_ins()`

Registration ultimately flows through:
- `append_function_to_built_ins(...)` in `src/monitor/lib/built_ins_utils.py`

## Current registration model

`configure_built_ins()` defines command groups, then registers each mapping with:
- `command`
- `function`
- `description`
- `group_description`

Many handlers are adapted through `_make_callable(...)`, which lets the built-in registry call them using the single-argument built-in calling convention.

## Current built-in calling convention

Handlers are generally invoked with a single optional argument containing the remainder of the command as text.

A simple built-in handler should therefore usually look like:

```python
def my_command(arg=None):
    print("hello")
```

If the handler takes no positional arguments, `_make_callable(...)` can adapt it.

If the handler requires additional dependencies or a different signature, register an explicit adapter, usually a lambda.

## Step 1: implement the handler

Put the implementation in an appropriate module.

Typical choices in the current codebase include:
- `src/monitor/lib/built_in_commands.py`
- `src/monitor/core/...` when tightly coupled to core runtime logic

Example:

```python
def echo_command(arg=None):
    if arg:
        print(arg)
    else:
        print("Nothing to echo.")
```

## Step 2: add the registration entry

In `src/monitor/core/built_ins.py`, add a new entry to the appropriate command group inside `configure_built_ins()`.

Example:

```python
{
    "command": "echo",
    "function": _make_callable(echo_command),
    "description": "Echo user-supplied text.",
}
```

Use the exact naming convention already used by the command group you are extending. Many built-ins are registered with plain names such as `macros` or `tasks`. For discovery, treat `:help` (aliases `:built_ins`, `?`) as the source of truth — not `:commands`, which lists terminal/internal catalog entries such as `llm<`.

If the function needs custom argument parsing or dependency injection, use a lambda:

```python
{
    "command": "complex",
    "function": lambda arg=None: complex_handler(parse_mode(arg)),
    "description": "Run a complex built-in.",
}
```

## Step 3: restart or re-run startup

`configure_built_ins()` runs during application startup in `src/monitor/app.py`.

After changing registrations, restart Monitor and confirm the new command appears in:

```text
:help
:help <your_command>
```

## Current examples in the codebase

`configure_built_ins()` currently registers built-ins such as:
- `help` / `built_ins` / `?`
- `commands` (terminal/internal catalog; prefer `:help` for built-ins)
- `history`
- `llm`
- `reasoning`
- `ttl`
- `max_tokens`
- `macros`
- `tools`
- `preferences`
- `tasks`
- `clear_tasks`
- `compact`
- `dump_metrics`
- `wiki_init`
- `wiki_lint`
- `wiki_fix`
- `rg`
- `agent`

These are good examples of both direct registrations and lambda adapters.

## Return values vs printing

In practice, built-ins should generally print their output directly.

That is the safest assumption for compatibility with the current built-in execution flow.

If you want to return a value instead, wrap the handler with a printer:

```python
def wrapper(arg=None):
    result = maybe_returning_handler(arg)
    if result is not None:
        print(result)
```

## Error handling guidance

For new built-ins:
- validate input early
- print useful usage/help text on bad arguments
- avoid uncaught exceptions when possible
- use explicit adapters when the handler needs more than a simple `arg=None`

## Related files
- `src/monitor/core/built_ins.py`
- `src/monitor/lib/built_ins_utils.py`
- `src/monitor/lib/built_in_commands.py`
- `src/monitor/lib/command_help.py`
