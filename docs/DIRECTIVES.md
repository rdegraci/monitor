# Using `directive<` in Monitor

This document describes the current `directive<` internal command.

The implementation lives in `src/monitor/core/commands.py`.

## What it does

`directive<` reads a file from `config.DIRECTIVES_DIR`, emits up to five `paramN=` lines, appends the file content, and sends the resulting text into Monitor's model pipeline.

It is an internal command, not a built-in registered through `configure_built_ins()`.

## Current syntax

```text
directive< <file_name> <param1> <param2> <param3> <param4> <param5>
```

Only the file name is required.

Example:
```text
directive< greet.prompt Alice "Acme Corp"
```

## Current execution model

The command definition in `src/monitor/core/commands.py` builds a shell function that:
- validates that a file name was provided
- resolves the file under `config.DIRECTIVES_DIR`
- prints:
  - `param1=...`
  - `param2=...`
  - `param3=...`
  - `param4=...`
  - `param5=...`
- concatenates the entire file contents
- returns the combined text to the internal command pipeline

Because the command is marked `internalize_to_llm=True`, successful output is then sent to the active model flow.

## Where directive files live

The directory is configured through `DIRECTIVES_DIR` in config and surfaced as `config.DIRECTIVES_DIR` at runtime.

The package seeding path in `src/monitor/__main__.py` currently creates example directive files such as:
- `directives/echo.prompt`
- `directives/greet.prompt`

## Important current behavior

- up to five parameters are supported
- if fewer parameters are supplied, blank `paramN=` lines are still emitted
- there is no client-side variable substitution inside the directive file
- the model receives plain text and must interpret the `paramN=` lines itself
- this command runs through the internal-command shell path, which executes via `zsh -c` after sourcing `~/.zshrc`
- this `~/.zshrc` behavior is specific to the general internal-command execution path and should not be assumed for `llm<`

## Example

Suppose `greet.prompt` contains:

```text
Write a short professional greeting using param1 as the person and param2 as the company.
```

Then this command:

```text
directive< greet.prompt Alice "Acme Corp"
```

causes Monitor to send text equivalent to:

```text
param1=Alice
param2=Acme Corp
param3=
param4=
param5=
Write a short professional greeting using param1 as the person and param2 as the company.
```

## Failure behavior

If the file is missing or unreadable, the shell command returns an error and the output is not forwarded to the model.

## Security note

Directive files are sent to the model as-is. Do not store secrets in them.

## Related docs
- `docs/INTERNAL_COMMANDS.md`
- `docs/GETTING_STARTED.md`
