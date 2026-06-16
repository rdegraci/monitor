# Internal Commands: `llm<` and `directive<`

The authoritative implementation for these commands lives in `src/monitor/core/commands.py`.

This document reflects the current code behavior.

## Overview

Monitor currently defines two internal commands in `INTERNAL_COMMANDS`:
- `llm<`
- `directive<`

These are not normal built-ins registered through `configure_built_ins()`. They are handled by the internal-command execution path in `src/monitor/core/commands.py`.

## `llm<`

### Purpose
`llm<` runs shell code locally, captures stdout, and forwards the resulting text into Monitor's model pipeline.

### Current syntax
```text
llm< <shell_code>
llm< <shell_code> >llm <user_prompt>
```

Examples:
```text
llm< "git status"
llm< "git diff HEAD~1..HEAD" >llm "Review this diff: ${result}"
llm< "sed -n '1,120p' src/monitor/core/commands.py" >llm "Explain this code: ${result}"
```

### Current behavior
The implementation:
1. parses the command line using `shlex` when possible
2. detects an optional literal `>llm` delimiter
3. runs the shell portion through `run_subprocess(...)` with shell execution enabled
4. captures stdout
5. assembles model input
6. calls `query(...)`
7. displays the result via the normal display path

### Prompt assembly rules
- if `>llm` is omitted, stdout becomes the full model input
- if a prompt is present and contains `${result}`, stdout replaces that placeholder
- if a prompt is present without `${result}`, the prompt is followed by stdout

### Failure behavior
- if shell execution fails, the error is surfaced and the LLM call is skipped
- if the assembled input is empty, Monitor warns and skips the LLM call

### Security note
`llm<` executes local shell code and sends captured output into the model pipeline. Do not use it with untrusted shell input or sensitive output unless you understand the consequences.

Unlike general internal commands such as `directive<`, `llm<` does not use the `zsh -c "source ~/.zshrc && ..."` execution path.

## `directive<`

### Purpose
`directive<` loads a directive file from `config.DIRECTIVES_DIR`, prepends parameter lines, and forwards the resulting text to the model pipeline.

### Current syntax
```text
directive< <file_name> <param1> <param2> <param3> <param4> <param5>
```

Example:
```text
directive< greet.prompt Alice "Acme Corp"
```

### Current behavior
The internal command definition builds a shell function that:
1. resolves `<file_name>` under `config.DIRECTIVES_DIR`
2. emits:
   - `param1=...`
   - `param2=...`
   - `param3=...`
   - `param4=...`
   - `param5=...`
3. concatenates the full directive file contents
4. returns the combined text
5. sends that combined text to the model pipeline because the command is marked `internalize_to_llm=True`

### Current details worth knowing
- up to five positional parameters are supported
- missing parameters are emitted as blank assignments
- there is no client-side template substitution inside the directive file
- the model sees plain text containing the `paramN=` lines followed by the file body
- `directive<` uses the general internal-command shell path, which runs via `zsh -c` after sourcing `~/.zshrc`

### Failure behavior
If the directive file cannot be read, the shell command returns an error and the output is not sent to the LLM.

## Difference between internal commands and built-ins

These commands are different from built-ins such as `commands`, `macros`, or `wiki_lint`.

- built-ins are registered in `src/monitor/core/built_ins.py`
- internal commands are defined in `src/monitor/core/commands.py`

`llm<` and `directive<` therefore participate in a different routing path from ordinary built-ins.

## Related files
- `src/monitor/core/commands.py`
- `src/monitor/core/query_service.py`
- `src/monitor/lib/command_utils.py`
- `docs/DIRECTIVES.md`

## Practical guidance

Use `llm<` when you want live local shell output analyzed.

Use `directive<` when you want to reuse prompt files stored under the configured directives directory.
