# Monitor System Architecture

This document summarizes the current Monitor architecture based on the code under `src/monitor/`.

## Top-level layout

Primary packages:
- `src/monitor/`
- `src/monitor/core/`
- `src/monitor/lib/`
- `src/monitor/tui/`
- `src/monitor_oop/`

The main production CLI path described here is the `monitor` package, with entrypoints in:
- `src/monitor/__main__.py`
- `src/monitor/app.py`

## Startup flow

### `src/monitor/__main__.py`
This module ensures user config files exist, then calls `monitor.app.main()`.

It seeds files such as:
- `config.yaml`
- `macros.json`
- `preferences.prompt`
- `model_config.json`
- `interactive_commands.json`
- `non_interactive_commands.json`
- directive prompt files under `directives/`

The interactive and non-interactive command catalogs are separate shipped
resources. The interactive catalog drives REPL/TUI routing, while the
non-interactive catalog supports script/server-style routing.

### `src/monitor/app.py`
This is the main runtime entrypoint for the classic Monitor application. It:
- parses CLI flags
- loads model config and environment globals
- starts logging
- configures subsystems
- freezes startup-time prompt and wiki paths
- registers built-ins and macros
- launches one of:
  - REPL chat loop
  - Flask server mode
  - script mode
  - TUI mode

Supported CLI flags currently include:
- `--server [host]`
- `--port`
- `--model`
- `--reset-config`
- `--force`
- `--models`
- `--version`
- `--debug`
- `--script`
- `--agent`
- `--tui`

`--agent` is a runtime modifier that enables agent-oriented behavior. It is not
a separate front-end mode.

## Major runtime modes

### 1. Interactive REPL
Default mode when no other special flag is provided.

Key pieces:
- `monitor.core.conversation.chat()`
- `monitor.core.command_processing`
- built-ins from `monitor.core.built_ins`
- macros from `monitor.lib.macros`

### 2. Script mode
`--script` runs commands from a file, one non-empty non-comment line at a time, through the same conversation input pipeline used by the REPL.

### 3. Server mode
`--server` launches a Flask development server built in `src/monitor/lib/server.py`.

Current API surface includes:
- `POST /cli`
- `GET /v1/models`
- `POST /v1/chat/completions`

If `MONITOR_SERVER_API_KEY` is set, `/v1/*` endpoints require Bearer auth.

The server is wrapped with `SingleRequestMiddleware`, which serializes requests with a process-local lock.

### 4. TUI mode
`--tui` launches the full-screen terminal UI in `src/monitor/tui/app.py` after the normal startup configuration path has run.

### 5. Agent mode
`--agent` enables sub-agent behavior by setting `config.AGENT = True`, which affects tool availability and write restrictions.

### 6. `--server` host behavior
`--server` accepts an optional host. If no host is provided, the runtime binds to `127.0.0.1`.

## Core package responsibilities

### `src/monitor/core/conversation.py`
Conversation orchestration for the interactive experience, including prompt flow, history updates, query execution, and tool-call integration.

### `src/monitor/core/command_processing.py`
Input routing and command classification between shell-like commands, built-ins, internals, and model flows.

### `src/monitor/core/commands.py`
Defines terminal-command registries and internal commands such as:
- `llm<`
- `directive<`

It also loads interactive and non-interactive command definitions from JSON files.

### `src/monitor/core/built_ins.py`
Registers built-in commands through `configure_built_ins()`.

Current built-ins include utility, persistence, diagnostics, response helper, data, indexing, workflow, wiki, and social commands.

Notable built-ins include:
- `commands`
- `history`
- `llm`
- `reasoning`
- `ttl`
- `max_tokens`
- `macros`
- `tasks`
- `clear_tasks`
- `compact`
- `dump_metrics`
- `wiki_init`
- `wiki_lint`
- `wiki_fix`
- `rg`
- `agent`

### `src/monitor/core/tooling.py`
Executes LLM tool calls, parses tool arguments, applies rate limiting, appends tool results into conversation history, and enforces several runtime safety rails.

Current safety-related behavior includes:
- nested tool-call depth cap via `MAX_TOOL_CALL_DEPTH`
- repeated-call loop detection via `MAX_REPEATED_TOOL_CALLS`
- write-tool blocking/scoping for sub-agents
- special handling for high-token file and directory operations

### `src/monitor/core/tools.py`
Configures which tool descriptions are exposed for the active provider/model. It dynamically selects between provider-neutral edit tools and provider-specific edit tool variants.

### `src/monitor/core/tooling.py`
Executes LLM tool calls, parses tool arguments, applies rate limiting, appends tool results into conversation history, and enforces runtime safety rails.

Current safety-related behavior includes:
- nested tool-call depth caps
- repeated-call loop detection
- write-tool blocking/scoping for sub-agents
- special handling for high-token file and directory operations
- failure-driven reasoning escalation for the current turn

The runtime status line shown in the REPL and TUI is built in `src/monitor/lib/display_output.py` and documented in `docs/STATUS_LINE.md`.

## Tool architecture

### Runtime callable registry
`src/monitor/lib/tool_definitions.py` defines:
- `AVAILABLE_TOOLS`
- `TOOL_DESCRIPTIONS`
- `GEMINI_TOOL_DESCRIPTIONS`
- `TOOL_STATE`

This is the core registry for model-callable tools.

### Tool loading helpers
`src/monitor/lib/tool_loading.py` provides helper functions for:
- adding and removing tools
- provider-specific tool-description transforms
- weather, memory, DB, modeling, and editing tool registration

Current provider-specific handling includes:
- Anthropic tool adaptation via `inject_anthropic_properties()`
- OpenAI tool adaptation via `inject_openai_properties()`
- Gemini-specific parallel description catalog

## Editing tool stack

Monitor currently exposes multiple file-edit pathways:

### Provider-neutral deterministic tools
Registered by `add_text_file_neutral_tools()`:
- `text_file_or_directory_view`
- `text_file_create`
- `text_file_str_replace_in_file`
- `text_file_insert_text_at_line`

### Mechanical multi-file editing
- `bulk_replace_in_files`

### Fallback natural-language editing
- `modify_source_code`

### Anthropic-native edit tool aliases
Depending on model/provider configuration, Monitor can also expose:
- `str_replace_based_edit_tool`
- `str_replace_editor`

## Macro system

### `src/monitor/lib/macros.py`
Owns macro state, loading, and display behavior.

Macro sources are layered with precedence:
1. public built-ins
2. file-defined macros
3. ephemeral runtime macros
4. private built-ins

Visible macros are grouped for display with metadata support.

### `src/monitor/lib/macro_utils.py`
Provides stateless helpers for:
- loading macro JSON
- loading macro metadata
- updating macro stores
- recursive expansion
- Tcl-backed macro expansion

Important security property:
- Tcl macros are executable host-side code, not a sandboxed template system

## HTTP server architecture

`src/monitor/lib/server.py` adapts Monitor into a local OpenAI-style API.

Key behavior:
- converts OpenAI-style chat messages into a single Monitor command
- invokes `internalize_command()`
- formats output as JSON or SSE
- supports serialized request handling through middleware
- warns when binding to non-localhost addresses

## Config system

`src/monitor/config.py` is the main configuration loader and global runtime state module.

It is responsible for:
- locating config files
- loading YAML and model JSON config
- environment loading from `.env`
- global state initialization
- subsystem bootstrapping
- logging configuration
- model switching at runtime

Important runtime-controlled features in config include:
- model mappings and windows
- rate limiting
- memory service flags
- reasoning behavior
- compaction and token budgeting
- server mode and agent mode
- sub-agent orchestration limits
- write-access policy for sub-agents
- tool output and file write caps

## Agent orchestration and reasoning escalation

Monitor supports sub-agents through tools and runtime config.

Relevant tools:
- `agent_create`
- `agent_list`
- `agent_send`
- `agent_gather`
- `agent_logfile`
- `agent_kill`

Relevant config/runtime controls include:
- `MONITOR_ENABLE_AGENT_ORCHESTRATION`
- `MONITOR_AGENT_DEPTH`
- `MONITOR_AGENT_MAX_DEPTH`
- `MONITOR_AGENT_MAX_BREADTH`
- `ORCHESTRATOR_MODEL`
- `ORCHESTRATOR_REASONING_EFFORT`
- `SUBAGENT_MODEL`
- `SUBAGENT_REASONING_EFFORT`
- `REASONING_BUMP_EFFORT`
- `ESCALATE_REASONING_ON_TOOL_FAILURE`

### Reasoning behavior

Monitor has two distinct runtime reasoning adjustments:
- a continuity bump for short follow-up confirmations, which can raise effort to `medium`
- a failure-driven escalation path, which can raise effort to `high` for the rest of the turn when tool output indicates a failure

### Role-based model selection

When `--agent` is active, Monitor applies the sub-agent model and effort defaults at startup if they are configured.
The orchestrator keeps the base model for the session, but can use the orchestrator role model transiently during collation turns.
An explicit `--model` override still wins over role-based defaults.
- `MONITOR_AGENT_MAX_TOTAL`
- `MONITOR_AGENT_HEARTBEAT_TIMEOUT`
- `MONITOR_AGENT_IDLE_TIMEOUT`
- `SUBAGENT_WRITE_ACCESS`
- `SUBAGENT_MEMORY_SERVICES`

Sub-agent write behavior is explicitly constrained in tooling, especially for write-capable tools.

## Wiki support

Monitor includes project-wiki support under `src/monitor/lib/monitor_wiki.py` and built-ins for:
- `wiki_init`
- `wiki_lint`
- `wiki_fix`

At startup, `configure_project_wiki_paths(startup_cwd)` freezes wiki identity/context for the session.

## Observability and logs

Logging setup originates in `config.py` and `monitor.lib.logging`.

The app creates:
- an application log file
- a per-process conversation log file

Conversation logs include the PID in the filename.

## OOP package note

The repository also contains `src/monitor_oop/`, which appears to be a separate or emerging architecture path. It includes its own `__main__.py`, core services, and presentation stack. The rest of this document focuses on the currently wired `monitor` runtime path used by `python -m monitor`.

## Architecture summary

At a high level:
1. `__main__` ensures config assets exist.
2. `app.py` loads config, logging, and subsystems.
3. built-ins, macros, tools, and prompt/wiki context are configured.
4. Monitor runs in REPL, script, server, TUI, or agent-oriented mode.
5. `core/` orchestrates conversation, command routing, and tool invocation.
6. `lib/` provides integrations, persistence, server adapters, macros, tools, and utilities.
