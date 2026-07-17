# Monitor Core README

This document describes the current responsibilities of `src/monitor/core`.

## Purpose of `core/`

The `core` package contains Monitor's runtime orchestration logic:
- conversation flow
- command routing
- built-in registration
- tool execution orchestration
- model/tool response adaptation
- mode switching

It sits above many helper modules in `monitor.lib`.

## File map

### `built_ins.py`
Registers built-in commands through `configure_built_ins()`.

Current command groups include:
- general utility commands
- session persistence
- diagnostics and metrics
- response helpers
- CSV data cleaning
- experimental tool management
- indexing and retrieval
- development workflow
- social and streaming

Notable registered built-ins include:
- `help` / `built_ins` / `?` (canonical discovery; see `command_help.py`)
- `commands`
- `history`
- `history_size`
- `llm` (alias `model`)
- `reasoning`
- `status` (status-line modes: minimal / coding / debug)
- `activity` (live turn feedback)
- `ttl`
- `max_tokens`
- `macros`
- `tools` (profiles: coding default; `full` widens)
- `preferences`
- `tasks`
- `clear_tasks`
- `next_steps`
- `reset_history`
- `compact`
- `break_chain`
- `dump_history`
- `load_history`
- `cost_debug`
- `dump_metrics`
- `less`
- `save_response`
- `copy_code`
- `wiki_init`
- `wiki_lint`
- `wiki_fix`
- `make_commit`
- `rg`
- `agent`

### `command_processing.py`
Routes incoming input between built-ins, shell-like commands, and model flows.

### `commands.py`
Maintains terminal command catalogs and internal command behavior.

Important internals currently defined here include:
- `llm<`
- `directive<`

It also classifies whether commands are interactive, non-interactive, or TTY-bound.

### `commit.py`
Provides commit-related command support such as `make_commit_command`.

### `conversation.py`
Implements the main conversation and query loop. This is one of the central runtime modules used by the REPL and related flows.

### `internalize_commands.py`
Supports routing or adaptation of commands that need special processing before being handled by the rest of the runtime.

### `llm.py`
Contains model invocation logic and related response handling paths.

### `llm_responses_adapter.py`
Adapts model responses into Monitor's internal response flow.

### `modes.py`
Contains mode-specific helpers such as design and development mode command behavior.

### `query_service.py`
Provides a query registration and lookup mechanism so external or adjacent systems can call the active conversation query function without tight coupling.

### `tooling.py`
Executes model-requested tools, handles argument parsing, updates history with tool results, and continues tool-call chains as needed.

Current responsibilities include:
- parsing tool args with `parse_function_args()`
- executing tools from `AVAILABLE_TOOLS`
- appending tool results to conversation history
- tool-call recursion depth checks
- repeated-call loop detection
- sub-agent write blocking and delegated scope enforcement
- rate limiting for expensive file and directory reads

### `tools.py`
Configures tool exposure based on the active provider/model.

Current provider branches include:
- Anthropic
- OpenAI
- Gemini
- xAI

The module decides whether to expose:
- provider-neutral deterministic editor tools
- Anthropic-native editor tool variants
- OpenAI-compatible fallback edit tools
- memory tools, subject to sub-agent gating

## Runtime flow summary

### REPL / interactive path
A typical interactive request goes through:
1. `app.py`
2. `conversation.chat()`
3. command and built-in classification
4. optional model invocation
5. optional tool-call execution through `tooling.py`
6. history/log updates

### Internal command path
Internal commands such as `llm<` and `directive<` are handled in `commands.py`.

- `llm<` executes shell code, captures stdout, and sends the assembled prompt into the model pipeline.
- `directive<` reads a directive file from `config.DIRECTIVES_DIR`, prepends `paramN=` lines, and sends the result to the model pipeline.

### Built-in path
Built-ins are registered in `built_ins.py` and exposed through the built-in registry helpers in `monitor.lib.built_ins_utils`.

### Tool-call path
When a model response contains tool calls:
1. tool calls are extracted from the response
2. `tooling.py` executes each requested tool
3. a tool result message is appended to conversation history
4. the model may be called again to continue the chain
5. chain execution is capped by depth and loop-safety checks

## Current safety behavior in `tooling.py`

Important guardrails currently wired into core tooling include:
- `MAX_TOOL_CALL_DEPTH`
- `MAX_REPEATED_TOOL_CALLS`
- guarded write-tool enforcement for sub-agents
- delegated write scope checks via `MONITOR_SUBAGENT_WRITE_SCOPE`
- write-tool restrictions driven by `SUBAGENT_WRITE_ACCESS`
- output-size related throttling for large file reads

Write-guarded tools currently include:
- `bulk_replace_in_files`
- `create_file`
- `modify_source_code`
- `str_replace_based_edit_tool`
- `str_replace_editor`
- `text_file_create`
- `text_file_insert_text_at_line`
- `text_file_str_replace_in_file`

## Core's relationship to `monitor.lib`

`core` depends heavily on `monitor.lib` for concrete helpers and integrations.

Examples:
- tool registries from `monitor.lib.tool_definitions`
- tool registration helpers from `monitor.lib.tool_loading`
- macros from `monitor.lib.macros`
- history and token/accounting helpers
- external integrations such as server support, git helpers, test running, and file editing

## Current extension points

If you are extending the current `core` package:
- add built-ins via `configure_built_ins()` in `built_ins.py`
- add or adapt internal command behavior in `commands.py`
- add tool registrations through `monitor.lib.tool_definitions` and `monitor.lib.tool_loading`
- update provider-specific tool selection in `tools.py`
- update tool execution and safety logic in `tooling.py` when the runtime contract changes

## Notes for contributors

A few codebase-accurate details to keep in mind:
- built-ins are grouped and registered centrally in `configure_built_ins()`
- internal commands live in `commands.py`, not in the built-in registry
- dynamic model changes should refresh provider-specific tool catalogs
- task planning is now part of the built-in surface via `tasks` and `clear_tasks`
- wiki operations are part of the development workflow command group

This file focuses on the currently active `monitor.core` runtime path used by the classic application.
