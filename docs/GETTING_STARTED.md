# Getting Started: Becoming Productive With Monitor

Welcome to Monitor. This guide reflects the current codebase and CLI behavior.

## What Monitor is

Monitor is an AI-assisted developer CLI with:
- an interactive REPL
- an optional Flask-based HTTP server
- built-in commands
- LLM-callable tools
- macros
- session task planning
- optional full-screen TUI mode

Core entrypoints live in:
- `src/monitor/__main__.py`
- `src/monitor/app.py`

## First launch

Typical startup:
```sh
python -m monitor
```

Useful startup flags:
```sh
python -m monitor --version
python -m monitor --models
python -m monitor --model gpt5
python -m monitor --debug
python -m monitor --script path/to/script.txt
python -m monitor --tui
python -m monitor --server 127.0.0.1 --port 5000
python -m monitor --agent
```

On first run, Monitor seeds user config files into your app config directory via `src/monitor/__main__.py`.

The shipped defaults include:
- `config.yaml`
- `macros.json`
- `preferences.prompt`
- `model_config.json`
- `interactive_commands.json`
- `non_interactive_commands.json`
- `directives/echo.prompt`
- `directives/greet.prompt`

`interactive_commands.json` supports interactive REPL/TUI routing, while `non_interactive_commands.json` supports script/server-style routing.

## Config and generated files

Monitor uses the user config directory reported by `appdirs`.

Common seeded files include:
- `config.yaml`
- `macros.json`
- `preferences.prompt`
- `model_config.json`
- `interactive_commands.json`
- `non_interactive_commands.json`
- `directives/echo.prompt`
- `directives/greet.prompt`

Logs are written under the configured log directory.

By default, main application and conversation logs are written under the user config directory's `logs` subdirectory, typically:
- `~/.config/monitor/logs` on Unix-like setups

Some auxiliary agent/session logs use separate cache-backed locations.

## Interactive usage

When the REPL starts, you should see:
```text
Monitor ready!
```

You can then:
- run shell commands
- run built-in commands
- ask natural-language questions
- invoke tools through the model

Monitor may also adjust reasoning effort while you work:
- short confirmation turns like `Sounds good. Proceed.` can bump effort to `medium` for that turn
- a tool failure can escalate effort to `high` for the remainder of the current turn
- if orchestration is enabled, `--agent` children can use a separate role model from the orchestrator

Examples:
```text
commands
history
macros
tasks
preferences
```

## Built-ins: use the exact registered names

To see the current built-ins:
```text
commands
```

Important built-ins currently registered in `src/monitor/core/built_ins.py` include:
- `commands`
- `history`
- `history_size`
- `llm`
- `model`
- `reasoning`
- `ttl`
- `max_tokens`
- `macros`
- `edit_macros`
- `edit_function_keys`
- `reload_macros`
- `tools`
- `preferences`
- `tasks`
- `clear_tasks`
- `next_steps`
- `reset_history`
- `compact`
- `dump_history`
- `load_history`
- `cost_debug`
- `dump_metrics`
- `less`
- `save_response`
- `copy_code`
- `cc`
- `clean_csv`
- `normalize_csv`
- `add_db_tools`
- `remove_db_tools`
- `add_modelling_tools`
- `remove_modelling_tools`
- `embed`
- `query`
- `index`
- `semstore`
- `power_user`
- `design_mode`
- `dev_mode`
- `wiki_init`
- `wiki_lint`
- `wiki_fix`
- `make_commit`
- `rg`
- `agent`
- `twitch`
- `joke`
- `tweet`
- `twitch_summary`
- `linkedin_summary`

Use the exact names shown by `commands`. If parser aliases or prefixed forms exist in some flows, treat them as compatibility behavior rather than the primary interface.

## Session task plan

Monitor has a task/todo system exposed both as built-ins and as tools.

Built-ins:
```text
tasks
clear_tasks
```

LLM-callable task tools include:
- `add_todo`
- `list_todos`
- `update_todo`
- `delete_todo`
- `clear_todos`

## Macros

Monitor supports persistent and ephemeral macros.

Persistent macros live in:
- `macros.json`

Runtime macros can be added in-session with:
```text
<name=value
```

Macro expansion defaults to these delimiters:
```yaml
macro_delimiters:
  open: "{{"
  close: "}}"
  escape: "\\"
```

Examples:
```text
<proj=~/projects/monitor
cd {{proj}}
macros
```

## Internal commands

Monitor has internal commands implemented in `src/monitor/core/commands.py`.

### `llm<`
Runs shell code, captures output, and sends it to the LLM pipeline.

Examples:
```text
llm< "git status"
llm< "git diff HEAD~1..HEAD" >llm "Review this diff: ${result}"
```

### `directive<`
Loads a directive file from `config.DIRECTIVES_DIR`, prepends up to five `paramN=` lines, and sends the resulting text to the LLM pipeline.

Example:
```text
directive< greet.prompt Alice "Acme Corp"
```

## Search, git, and file work

Monitor exposes several developer tools through the model and supporting command layers.

Examples of common tool-backed work:
- git inspection
- ripgrep search
- file viewing
- deterministic text editing
- test runs
- type checking

Examples of current tool names:
- `perform_git_status`
- `perform_git_diff`
- `perform_git_diff_file`
- `perform_git_diff_previous`
- `perform_git_show`
- `search_commit_history`
- `blame_lines`
- `perform_git_diff_range`
- `find_files`
- `ripgrep_search_tool`
- `cat_file`
- `cat_file_range`
- `list_directory_contents`
- `run_python_tests`
- `type_check_python`

## Deterministic file editing tools

Monitor currently supports several precise editing tools in addition to the fallback `modify_source_code` flow.

Prefer these when possible:
- `text_file_or_directory_view`
- `text_file_create`
- `text_file_str_replace_in_file`
- `text_file_insert_text_at_line`
- `bulk_replace_in_files`

These are better for exact, reviewable edits than fuzzy natural-language rewriting.

## Server mode

Monitor can expose a local HTTP API:
```sh
python -m monitor --server 127.0.0.1 --port 5000
```

`--server` also accepts no host argument, in which case it binds to `127.0.0.1`.

The server implementation lives in `src/monitor/lib/server.py`.

Important endpoints:
- `POST /cli`
- `GET /v1/models`
- `POST /v1/chat/completions`

If `MONITOR_SERVER_API_KEY` is set, `/v1/*` endpoints require:
```text
Authorization: Bearer <token>
```

Security note:
- avoid binding the Flask dev server to non-localhost interfaces unless you understand the risk and protect it properly

## TUI mode

Monitor also supports a full-screen TUI launch path:
```sh
python -m monitor --tui
```

The main TUI implementation lives under:
- `src/monitor/tui/app.py`

## Agent orchestration

Monitor has sub-agent support with tools such as:
- `agent_create`
- `agent_list`
- `agent_send`
- `agent_gather`
- `agent_logfile`
- `agent_kill`

Related config/runtime controls include:
- `MONITOR_ENABLE_AGENT_ORCHESTRATION`
- `SUBAGENT_WRITE_ACCESS`
- `MONITOR_AGENT_MAX_DEPTH`
- `MONITOR_AGENT_MAX_BREADTH`
- `MONITOR_AGENT_MAX_TOTAL`

## Wiki workflow

Monitor includes project wiki support and wiki built-ins:
- `wiki_init`
- `wiki_lint`
- `wiki_fix`

Project wiki session paths are configured at startup using the current working directory.

## Quick cheat sheet

| Action | Example |
|---|---|
| Start REPL | `python -m monitor` |
| Start TUI | `python -m monitor --tui` |
| Start server | `python -m monitor --server 127.0.0.1 --port 5000` |
| List models | `python -m monitor --models` |
| Switch model at startup | `python -m monitor --model gpt5` |
| Run a script | `python -m monitor --script ./script.txt` |
| Show commands | `commands` |
| Show macros | `macros` |
| Show task plan | `tasks` |
| Clear task plan | `clear_tasks` |
| Add ephemeral macro | `<name=value` |
| Use macro | `{{name}}` |
| Ask for git status through internal command | `llm< "git status"` |

For more detail, see the architecture and module docs in `docs/`.
