# Monitor lib README

This document describes the current `src/monitor/lib` layer.

## Purpose of `monitor.lib`

`monitor.lib` contains most of the reusable implementation details that the core runtime depends on:
- tool implementations and registries
- macros and macro utilities
- server support
- persistence and external integrations
- git, search, filesystem, and editing helpers
- logging, rate limiting, token accounting, and presentation helpers

## Important current modules

### Tool and registry modules
- `tool_definitions.py`
- `tool_loading.py`
- `tool_profiles.py` — profiles `minimal` / `coding` (default) / `review` / `full`, groups, leases
- `tool_failures.py` — failure categories, read/symbol budgets, exact-arg loops
- `code_symbols.py` — on-demand `file_outline` / `find_symbol` with cache
- `tool_text.py`
- `bulk_replace.py`
- `find_files.py`
- `text_file_editor.py`
- `type_checker.py`
- `test_runner.py`
- `optional_deps.py` — soft imports for extras with install hints

### Onboarding and REPL UX modules
- `check_config.py` — secret-safe `--check-config`
- `command_help.py` — `:help` task groups
- `activity.py` — live turn / tool status line
- `status_line.py` — `minimal` / `coding` / `debug` status modes

### Macro modules
- `macros.py`
- `macro_utils.py`

### HTTP/server modules
- `server.py`

### Wiki modules
- `monitor_wiki.py`
- `monitor_wiki_linter.py`
- `built_ins_wiki_utils.py`

### ChromaDB modules (optional `.[chroma]` extra)
- `chroma_client.py` — embedded PersistentClient operations
- `chroma_cli.py` — `chroma-db` console script / `bin/chroma-db` entrypoint

### Support and integration modules
- `git.py`
- `git_history.py`
- `commit_analyzer.py` — branch commit analysis for `:next_steps` and commit-message prompt building for `:make_commit`
- `ripgrep_search.py`
- `redis_utils.py`
- `rate_limiter.py`
- `token_management.py`
- `llm_usage_utils.py` — canonical token extraction, usage deltas, and truncation helpers
- `llm_utils.py` — LLM call orchestration; re-exports selected helpers from `llm_usage_utils.py`
- `logging.py`
- `system_prompt.py`
- `external_services.py`
- `agent_orchestrator.py`
- `instances.py` — `--status-all` / `--activate`

## Tool registry architecture

### `tool_definitions.py`
Defines the current tool registry surface:
- `AVAILABLE_TOOLS`
- `TOOL_DESCRIPTIONS`
- `GEMINI_TOOL_DESCRIPTIONS`
- `TOOL_STATE`

Current callable tools include categories such as:
- git inspection
- file and directory viewing
- file creation and editing
- memory tools
- search tools
- web search
- tests and type checking
- todo/task tools
- sub-agent tools
- weather and DB tooling

### `code_symbols.py`

Provides optional tree-sitter structural tools in the `core_read` group:

- `file_outline(path, kind, max_results)` — one-file outline
- `find_symbol(query, path, kind, max_results)` — ranked repo definition lookup

Languages: Python, JavaScript, TypeScript/TSX, Go, Rust, Swift. Install via
`pip install '.[symbols]'`. Results are requested on demand; no repo map is
injected into each prompt. Parsed symbols are cached under the platform
user-cache directory by path, mtime, size, and language.

Examples of current tool names:
- `perform_git_status`
- `perform_git_diff`
- `perform_git_diff_file`
- `perform_git_diff_previous`
- `perform_git_show`
- `search_commit_history`
- `blame_lines`
- `perform_git_diff_range`
- `list_directory_contents`
- `cat_file`
- `cat_file_range`
- `create_file`
- `modify_source_code`
- `find_files`
- `file_outline`
- `find_symbol`
- `run_python_tests`
- `type_check_python`
- `text_file_or_directory_view`
- `text_file_create`
- `text_file_str_replace_in_file`
- `text_file_insert_text_at_line`
- `bulk_replace_in_files`
- `ripgrep_search_tool`
- `add_todo`
- `list_todos`
- `update_todo`
- `delete_todo`
- `clear_todos`
- `agent_create`
- `agent_list`
- `agent_send`
- `agent_gather`
- `agent_logfile`
- `agent_kill`
- `make_directory`

### `tool_loading.py`
Provides helpers for:
- enabling and disabling tools
- registering tool descriptions
- converting descriptions for OpenAI and Anthropic
- model/provider-specific edit tool setup

It currently exposes registration helpers for:
- weather tools (`add_weather_tools`)
- memory tools (`add_memory_tools`)
- DB tools (`add_db_tools` / `remove_db_tools`)
- modeling tools (`add_modelling_tools` / `remove_modelling_tools`)
- provider-neutral text editor tools
- Anthropic-native editor tools
- OpenAI editor tools

Paired `remove_*` helpers exist for tool families that `configure_tools()` toggles at runtime (DB, modeling, editor catalogs). Weather and memory tools are enabled during startup and are not removed dynamically.

### `tool_profiles.py`
Defines advertised tool **groups** and profiles (`minimal`, `coding`, `review`,
`full`). Default profile `coding` includes core_read, task, edit, verify, and
memory. Network, database, and agent groups stay opt-in (`:tools full` or
auto-widen leases).

### `tool_failures.py`
Maps tool errors to short `[category]` messages with one recovery step, and
enforces exact-arg loop detection plus per-path read budgets for view tools.

## Current editing stack

Preferred order for the model: create → str_replace → insert → bulk →
`modify_source_code` last.

### `text_file_editor.py`
Provides deterministic text editing helpers used as preferred exact-edit tools.

Current user-facing tool functions include:
- `text_file_or_directory_view`
- `text_file_create`
- `text_file_str_replace_in_file`
- `text_file_insert_text_at_line`
- `str_replace_based_edit_tool`

### `bulk_replace.py`
Provides deterministic mechanical multi-file editing through:
- `bulk_replace_in_files`

### `commit_analyzer.py`
Provides LLM-backed branch analysis used by the `:next_steps` built-in:
- `CommitAnalyzer` — fetches `git log -p` for a branch range, summarizes purpose, suggests next steps
- `next_steps(branch, main_branch)` — prints colored diff, summary, and numbered suggestions
- `build_commit_message_query_input(...)` — builds the macro-expanded prompt for `:make_commit`

The `:next_steps` adapter in `core/built_ins.py` parses `<branch> [<main_branch>]` and delegates here. When `<main_branch>` is omitted, the repo default branch is auto-detected via `git.get_default_branch()`.

### `protocol_engine.py`
Contains the underlying natural-language editing engine used by the fallback `modify_source_code` tool.

## Macro system

### `macros.py`
Maintains macro state and macro presentation.

Current sources of macro values include:
- built-in public macros
- file-defined macros
- ephemeral runtime macros
- private built-ins

It also supports grouped visible macro listings using metadata loaded from `macros.json`.

### `macro_utils.py`
Handles:
- reading macro JSON
- reading metadata sections such as `_groups` and `_macro_meta`
- recursive macro expansion
- optional Tcl-backed macro execution

Important security note:
- Tcl macros execute host-side code and should be treated as executable content, not passive configuration

## Server support

### `server.py`
Creates the current Flask development server used by `python -m monitor --server ...`.

Current features include:
- serialized request processing via `SingleRequestMiddleware`
- `POST /cli` — simple JSON command bridge (`{"command": "<text>"}`)
- `GET /v1/models`
- `POST /v1/chat/completions`
- Bearer-token protection for `/v1/*` when `MONITOR_SERVER_API_KEY` is configured
- SSE streaming support for chat completions

## Agent support

Several modules support sub-agent workflows.

Examples:
- `agent_orchestrator.py`
- `agent_listener.py`
- `agent_reporter.py`
- `subagent_logging.py`
- `agent/` package helpers

Current tool-layer support exposes:
- create
- list
- send
- gather
- logfile lookup
- kill

## Wiki support

Wiki-related behavior is implemented across:
- `monitor_wiki.py`
- `monitor_wiki_linter.py`
- `built_ins_wiki_utils.py`

This supports the built-ins:
- `wiki_init`
- `wiki_lint`
- `wiki_fix`

Project wiki context is frozen at startup from the initial working directory.

## Config-adjacent infrastructure

The `lib` layer also contains many modules used during global runtime setup or steady-state operation:
- `logging.py`
- `rate_limiter.py`
- `token_management.py`
- `llm_usage_utils.py`
- `preferences.py`
- `keyboard.py`
- `voice_to_text.py`
- `system_prompt.py`
- `semantic_store.py`
- `external_services.py`

## Practical guidance for contributors

When extending `monitor.lib`:
- prefer adding focused helper modules rather than growing unrelated ones
- register model-callable tools through `tool_definitions.py` and `tool_loading.py`
- use deterministic edit tools where exact behavior is possible
- treat macro and server changes as high-sensitivity areas because they affect trust boundaries and external surface area

## Summary

`monitor.lib` is the implementation-heavy layer of the current Monitor codebase. If `core/` is the orchestration layer, `lib/` is where most concrete integrations, utilities, safety rails, and reusable tool logic live.
