# Monitor System Architecture

This document summarizes the current Monitor architecture based on the code under `src/monitor/`.

## Top-level layout

Primary packages:
- `src/monitor/` — **production** runtime
- `src/monitor/core/`
- `src/monitor/lib/`
- `src/monitor/tui/`
- `src/monitor_oop/` — **experimental** alternate stack (not the recommended entry point)

The main production CLI path described here is the `monitor` package, with entrypoints in:
- `src/monitor/__main__.py`
- `src/monitor/app.py`

Console scripts: `monitor` (production), `monitor-oop` (experimental).

## Startup flow

### `src/monitor/__main__.py`
This module seeds user config files when missing (never overwrites existing
files), then calls `monitor.app.main()`.

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
- `--check-config` (secret-safe readiness report; exits)
- `--version`
- `--debug`
- `--script`
- `--agent`
- `--tui`
- `--status-all` (list running Monitor instances; fast-path in `__main__.py`)
- `--activate <tty>` (focus the Terminal/iTerm tab for a Monitor TTY)

`--check-config` validates config-file presence, model, tool profile, status-line
mode, daily budget, and provider API-key *presence* without printing key values
(`src/monitor/lib/check_config.py`).

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
- `help` / `?` (canonical discovery)
- `commands`
- `history`
- `llm`
- `reasoning`
- `status` / `activity`
- `ttl`
- `max_tokens`
- `macros`
- `tools`
- `tasks`
- `clear_tasks`
- `compact` / `break_chain` / `reset_history`
- `dump_metrics`
- `symbols` (optional parsers: readiness / langs / cache)
- `wiki_init`
- `wiki_lint`
- `wiki_fix`
- `rg`
- `agent`

### `src/monitor/core/tools.py`
Configures which tool descriptions are exposed for the active provider/model,
including **tool profiles** (`src/monitor/lib/tool_profiles.py`). Static
profiles are `minimal`, `coding` (default), `review`, and `full`. The default
`coding` profile advertises core_read, task, edit, verify, and memory groups;
network/db/agent stay opt-in via `:tools full` or auto-widen leases.

### `src/monitor/core/tooling.py`
Executes LLM tool calls, parses tool arguments, applies rate limiting, appends
tool results into conversation history, and enforces runtime safety rails.

Current safety-related behavior includes:
- nested tool-call depth caps (`MAX_TOOL_CALL_DEPTH`)
- repeated-call loop detection (`MAX_REPEATED_TOOL_CALLS`)
- per-path read budget for `cat_file` / range views (`MAX_PATH_READS_PER_TURN`)
- per-turn on-demand symbol budget (`MAX_SYMBOL_QUERIES_PER_TURN`)
- actionable failure categories (`src/monitor/lib/tool_failures.py`)
- write-tool blocking/scoping for sub-agents
- special handling for high-token file and directory operations
- failure-driven reasoning escalation for the current turn
- live turn activity updates (`src/monitor/lib/activity.py`)

The runtime status line shown in the REPL and TUI is built in
`src/monitor/lib/display_output.py`, filtered by
`src/monitor/lib/status_line.py`, and documented in `docs/STATUS_LINE.md`.

## Tool architecture

### Runtime callable registry
`src/monitor/lib/tool_definitions.py` defines:
- `AVAILABLE_TOOLS`
- `TOOL_DESCRIPTIONS`
- `GEMINI_TOOL_DESCRIPTIONS`
- `TOOL_STATE`

This is the core registry for model-callable tools. What the model *sees* is
further filtered by the active tool profile.

### On-demand code symbols

`src/monitor/lib/code_symbols.py` provides `file_outline` and `find_symbol` in
the default `core_read` group. Optional tree-sitter grammars support Python,
JavaScript, TypeScript/TSX, Go, Rust, and Swift. The model requests structural
context as needed; Monitor does not attach an always-on repository map.

Git-backed enumeration respects `.gitignore`; parsed symbols are cached outside
the repository in the platform user-cache directory. Tool telemetry records
counts, cache hits, files scanned, result counts, and truncation only—never
queries or symbol output.

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

Monitor currently exposes multiple file-edit pathways. Preferred order:

1. `text_file_create`
2. `text_file_str_replace_in_file`
3. `text_file_insert_text_at_line`
4. `bulk_replace_in_files`
5. `modify_source_code` (NL fallback, last)

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
- Responses follow-up budgeting reserves and safety ratio
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
- `MONITOR_AGENT_MAX_TOTAL`
- `MONITOR_AGENT_HEARTBEAT_TIMEOUT`
- `MONITOR_AGENT_IDLE_TIMEOUT`
- `ORCHESTRATOR_MODEL`
- `ORCHESTRATOR_REASONING_EFFORT`
- `SUBAGENT_MODEL`
- `SUBAGENT_REASONING_EFFORT`
- `SUBAGENT_WRITE_ACCESS`
- `SUBAGENT_MEMORY_SERVICES`
- `REASONING_BUMP_EFFORT`
- `ESCALATE_REASONING_ON_TOOL_FAILURE`

Sub-agent write behavior is explicitly constrained in tooling, especially for write-capable tools.

### Reasoning behavior

Monitor has two distinct runtime reasoning adjustments:
- a continuity bump for short follow-up confirmations, which can raise effort to `medium`
- a failure-driven escalation path, which can raise effort to `high` for the rest of the turn when tool output indicates a failure

### Responses follow-up budgeting

Responses API follow-up calls are preflighted in
`src/monitor/core/llm_responses_adapter.py` with a reserve-aware budgeting
policy.

Current behavior includes:
- request-shape classification for fresh, chained, tool-result, and
  summarization follow-ups,
- usable-window calculation from `MODEL_INPUT_WINDOW` or
  `MODEL_CONTEXT_WINDOW`,
- config-driven safety ratio and hidden-chain reserves,
- measured tool-schema and structured `function_call_output` shell reserves
  using serialized structure token counting,
- structured logging for both budget preflight decisions and actual
  `context_length_exceeded` failures,
- fallback into the existing summarization/rebase path when a normal tool
  follow-up cannot be admitted safely.

Relevant config keys include:
- `FOLLOWUP_BASE_SAFETY_RATIO`
- `FOLLOWUP_TOPLEVEL_RESERVE_TOKENS`
- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS`
- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`

### Role-based model selection

When `--agent` is active, Monitor applies the sub-agent model and effort defaults at startup if they are configured.
The orchestrator keeps the base model for the session, but can use the orchestrator role model transiently during collation turns.
An explicit `--model` override still wins over role-based defaults.

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

## OOP package note (experimental)

The repository also contains `src/monitor_oop/` and the `monitor-oop` console
script. This is an **experimental** alternate architecture (own `__main__.py`,
services, and presentation stack). It is **not** the recommended production
entry point. Prefer `monitor` / `python -m monitor` for day-to-day coding.
Primary onboarding docs intentionally omit `monitor_oop` except as a warning.

## Architecture summary

At a high level:
1. `__main__` ensures config assets exist.
2. `app.py` loads config, logging, and subsystems.
3. built-ins, macros, tools, and prompt/wiki context are configured.
4. Monitor runs in REPL, script, server, TUI, or agent-oriented mode.
5. `core/` orchestrates conversation, command routing, and tool invocation.
6. `lib/` provides integrations, persistence, server adapters, macros, tools, and utilities.
