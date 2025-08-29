
# How to Add a New Built-In Command

This guide explains how to add a new built-in command to your application, enabling you to extend the interactive CLI with your own functionality.

---

## Step 1: Define Your Command Function

Create your command handler as a Python function. Place it in `core/built_ins.py` for simple commands, or in another appropriate module for more complex logic.

**Example:**
```python
def hello_world_command(arg=None):
    """Simple command that prints Hello, World!"""
    print("Hello, World!")
```

---

## Step 2: Register the Command in `configure_built_ins()`

In `core/built_ins.py`, locate the `configure_built_ins()` function. Built-in commands are registered here in grouped dictionaries. Add your command to an appropriate group (such as "General utility commands") or create a new group if needed.

**Example (Add to General utility commands):**
```python
command_groups: List[Dict[str, Any]] = [
    {
        "group_description": "General utility commands",
        "commands": [
            # ...existing commands...
            {
                "command": ":hello",
                "function": hello_world_command,
                "description": "Print 'Hello, World!' to the screen.",
            },
        ],
    },
    # ... other groups ...
]
```

---

## Step 3: (Re)Start the Application

Restart your app so it loads the updated built-in command registry. Your new command will now be registered and available.

---

## Step 4: Use the Command

At the CLI prompt, type:
```
:hello
```
You should see:
```
Hello, World!
```
---

## Tips
- Handlers can accept arguments from the user by utilizing the `arg` parameter.
- Prefix custom commands with a colon (`:`) to avoid naming collisions.
- Include descriptive docstrings and help text for clarity.
- Check existing code in `core/built_ins.py` for more examples (including commands with arguments, utility commands, etc).

---

## Writing Commands That Accept Arguments

Built-in command functions can accept user-supplied arguments from the CLI by using the `arg` parameter. The argument will contain everything typed by the user after the command name.

**Example:**
```python
def echo_command(arg=None):
    """Echoes the provided arguments back to the user."""
    if arg:
        print(arg)
    else:
        print("Nothing to echo.")
```
Register as:
```python
{
    "command": ":echo",
    "function": echo_command,
    "description": "Print back user-supplied text (usage: :echo your text)",
}
```
Usage at the prompt:
```
:echo Hello World!
```
This displays:
```
Hello World!
```

---

## Returning Values From Built-In Commands

A built-in command may return a value rather than (or in addition to) printing directly. The command processor will print the returned value, or make it available for piping if supported.

**Example:**
```python
def double_command(arg=None):
    """Doubles a numeric input and returns the result."""
    try:
        num = float(arg)
        return num * 2
    except (TypeError, ValueError):
        return "Please enter a valid number."
```
Register as:
```python
{
    "command": ":double",
    "function": double_command,
    "description": "Double a number (usage: :double 5)",
}
```
When used as `:double 5`, the output is:
```
10.0
```

---

## Error Handling Best Practices for Built-In Commands

Handle errors gracefully within your built-in command functions to provide helpful feedback and avoid crashing the app.

**Guidelines:**
- Use `try`/`except` blocks to catch potential errors.
- Return or print clear, user-friendly error messages.
- Validate and sanitize input received via `arg`.
- Avoid raising uncaught exceptions.

**Example:**
```python
def safe_divide_command(arg=None):
    """Divides two numbers, reporting errors for bad inputs."""
    try:
        parts = arg.split()
        if len(parts) != 2:
            return "Usage: :divide num1 num2"
        num1, num2 = float(parts[0]), float(parts[1])
        if num2 == 0:
            return "Cannot divide by zero."
        return num1 / num2
    except (ValueError, TypeError, AttributeError):
        return "Please provide two numeric values."
```

---

## Displaying Help for Custom Commands

To display help for your custom commands:
- Add a descriptive `description` when registering the command. This will usually show when the user types `:help` or similar.
- Make sure your handler function contains a docstring with usage information. This can be shown when help is requested for a specific command.

**Example:**
```python
def my_command(arg=None):
    """
    Do something useful.

    Usage: :my_command [options]
    """
    # implementation here
```
When you register:
```python
{
    "command": ":my_command",
    "function": my_command,
    "description": "Do something useful (see :help :my_command)",
}
```

---

## Quick Reference Table

| Step | Action                                                                  |
|------|-------------------------------------------------------------------------|
| 1    | Define your handler function                                            |
| 2    | Register it in `configure_built_ins()`                                 |
| 3    | Restart the app                                                        |
| 4    | Use the command by typing `:<your_command>` at the CLI                 |

---

You're all set to extend your CLI with new custom commands!


