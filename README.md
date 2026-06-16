# Monitor

Monitor is an AI-assisted developer CLI with an interactive REPL, built-in
commands, LLM-callable tools, macros, task planning, and an optional local HTTP
server.

## Features

- Interactive REPL for shell work and LLM-assisted development
- Built-in commands for history, tasks, macros, model settings, wiki workflows,
  and diagnostics
- Internal commands such as `llm<` and `directive<`
- LLM-callable tools for git inspection, search, file editing, tests, type
  checking, memory, todo management, and sub-agent orchestration
- Persistent and ephemeral macros
- Deterministic file editing tools plus a fallback natural-language editor
- Local OpenAI-style HTTP API
- Optional full-screen TUI mode

## Requirements

- Python 3.10+
- pip
- Platform-specific optional dependencies for some features

## Installation

### 1. Clone the repository

```sh
git clone <your-repo-url>
cd <repo-dir>
```

### 2. Install Monitor

```sh
pip install .
```

For development:

```sh
pip install -e .
```

### 3. Optional: create a user `.env`

```sh
mkdir -p ~/.config/monitor
cp src/monitor/dot_env_example ~/.config/monitor/.env
$EDITOR ~/.config/monitor/.env
```

For example:

```dotenv
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
XAI_API_KEY=...
```

Monitor also loads a project-local `.env` when present. The load order is:

1. project `.env`
2. `~/.config/monitor/.env`

Values in the user file override values from the project file.

### 4. Optional platform dependencies

Some features depend on external tools such as:

- `ripgrep`
- `git`
- `redis`
- `duckdb`
- `ffmpeg`
- `graphviz`
- `libmagic`
- `portaudio`

On macOS with Homebrew:

```sh
brew install pkg-config portaudio libmagic ffmpeg graphviz ripgrep redis duckdb git
brew services start redis
```

## Quick start

Start the REPL:

```sh
python -m monitor
```

or:

```sh
monitor
```

Startup begins in `src/monitor/__main__.py`, which copies packaged defaults into
the user config directory only when those files are missing, then delegates to
`src/monitor/app.py`.

Packaged defaults seeded on startup include:

- `config.yaml`
- `macros.json`
- `preferences.prompt`
- `model_config.json`
- `interactive_commands.json`
- `non_interactive_commands.json`
- `directives/echo.prompt`
- `directives/greet.prompt`

For project-local prompt guidance, `AGENTS.md` is authoritative when present in
the startup scope. In that case, Monitor does not read project-local
`MONITOR.md` or `MONITOR_CONVENTIONS.md` overrides.

## Common usage

### Show terminal/internal command names

```text
commands
```

`commands` lists terminal command entries and internal commands such as `llm<`
and `directive<`. It does not list built-in slash/colon commands.

### Built-in commands

Built-ins are a separate command surface. Common examples include:

- `tasks`
- `clear_tasks`
- `macros`
- `tools`
- `history`
- `llm`
- `model`
- `reasoning`
- `compact`
- `rg`
- `agent`

Use the exact names shown by the relevant built-in listings and prompts.
Depending on front-end/input mode, built-ins are typically invoked with `:` or
`/`, for example `:tasks` or `/tasks`.

### Show visible macros

```text
macros
```

This shows visible macros grouped by metadata:

- built-in public macros
- persistent file macros
- runtime/ephemeral macros

Private internal macros are not shown in the normal listing.

### Show the current task plan

```text
:tasks
```

Clear it with:

```text
:clear_tasks
```

The task plan is per-session and backed by the same todo/task tool surface the
model uses internally.

### Add an ephemeral macro

```text
<proj=~/projects/monitor
```

Then use it with:

```text
cd {{proj}}
```

Ephemeral macros are session-only.

For persistent macros, use `:edit_macros` and `:reload_macros`.

### Run an internal command through the LLM pipeline

```text
llm< "git status"
llm< "git diff HEAD~1..HEAD" >llm "Review this diff: ${result}"
```

`llm<` is an internal command that runs shell code, captures stdout, and sends
it to the model pipeline. Unlike general internal commands such as `directive<`,
it does not use the `zsh -c "source ~/.zshrc && ..."` execution path.

### Use a directive file

```text
directive< greet.prompt Alice "Acme Corp"
```

`directive< <file> [arg1 ... arg5]` loads a directive file from the configured
`DIRECTIVES_DIR`, prepends up to five `paramN=` lines, and sends the combined
text to the model pipeline.

### Macro safety note

Macros support Tcl evaluation in both `{{tcl ...}}` and bare `tcl ...` forms.
This is executable code, not sandboxed templating. Treat `macros.json` and
runtime-added Tcl macros as trusted code only.

## CLI modes and flags

Monitor runs in one of four execution paths:

- REPL mode
- script mode
- server mode
- TUI mode

The `--agent` flag is a behavior modifier that enables agent-oriented runtime
behavior; it is not a separate front-end mode by itself.

### REPL mode

```sh
python -m monitor
```

### TUI mode

```sh
python -m monitor --tui
```

### Script mode

```sh
python -m monitor --script path/to/script.txt
```

In script mode, Monitor executes one non-empty, non-comment line at a time
through the same input pipeline used by the interactive session.

### Server mode

```sh
python -m monitor --server
python -m monitor --server 127.0.0.1 --port 5000
python -m monitor --server 0.0.0.0 --port 5000
```

`--server` optionally accepts a host value. If passed without one, it binds to
`127.0.0.1`.

### Agent behavior flag

```sh
python -m monitor --agent
```

### Other useful flags

```sh
python -m monitor --version
python -m monitor --models
python -m monitor --model gpt5
python -m monitor --debug
```

## Server API

Monitor exposes a local HTTP API in server mode.

### Endpoints

- `POST /cli`
- `GET /v1/models`
- `POST /v1/chat/completions`

### Behavior

- `POST /cli` runs a raw internal command from a JSON payload like:

  ```json
  {"command": "..."}
  ```

- `GET /v1/models` returns an OpenAI-style model list and includes a
  non-standard top-level `active_model` field.

- `POST /v1/chat/completions` accepts OpenAI-style chat payloads, extracts the
  last user message as a single CLI command, runs it through Monitor's internal
  command pipeline, and returns the result in an OpenAI-compatible response
  envelope.

- `POST /v1/chat/completions` also supports `stream: true` and returns
  Server-Sent Events.

### Authentication

If `MONITOR_SERVER_API_KEY` is set, `/v1/*` endpoints require:

```text
Authorization: Bearer <token>
```

This check applies to `/v1/*` routes only. `POST /cli` is not covered by that
Bearer-token check.

### Concurrency

The Flask app is wrapped with `SingleRequestMiddleware`, so requests are fully
serialized. Only one request is processed at a time, and the lock is held until
response iteration completes.

### Security note

The built-in server is intended for local development and single-user workflows.
Binding to anything other than `127.0.0.1` or `localhost` can expose arbitrary
command execution via `/cli` and `/v1` endpoints.

## Configuration

Monitor uses platform-specific config directories via `appdirs`.
Typical user config locations are:

- Linux: `~/.config/monitor`
- macOS: `~/Library/Application Support/monitor`
- Windows: `%APPDATA%/monitor`

For key config files such as `config.yaml` and `model_config.json`, Monitor
resolves the user config file first and falls back to the site config directory
when needed.

For project-local prompt files in the startup scope, precedence is:

1. `AGENTS.md`
2. otherwise `MONITOR.md` or `build/MONITOR.md`
3. otherwise packaged/appdir fallback for Monitor instructions

When `AGENTS.md` is present, project-local `MONITOR.md` and
`MONITOR_CONVENTIONS.md` are not read.

### Resetting config

`--reset-config` restores a smaller reset set than first-run seeding. It backs
up and restores:

- `config.yaml`
- `macros.json`
- `model_config.json`
- `preferences.prompt`
- `public_commands.json`

## Logs

Logging is configured from the `logging` section in `config.yaml`.

If unset, current startup defaults place logs under:

- `~/.config/monitor/logs`

The main application and conversation logs use startup-scoped and process-
specific filenames. Sub-agent sessions may also produce separate transcript/log
files; use the agent logfile tooling to inspect those paths.

## LLM-callable tools

Monitor's tool registry includes:

- git and history inspection
- filesystem access
- deterministic text editing
- ripgrep search
- Python tests and type checking
- todo/task tools
- memory tools
- sub-agent orchestration
- web and weather helpers
- selected DB/model helper commands

Examples of current tool names include:

- `perform_git_status`
- `perform_git_diff`
- `search_commit_history`
- `cat_file`
- `find_files`
- `text_file_or_directory_view`
- `text_file_create`
- `text_file_str_replace_in_file`
- `text_file_insert_text_at_line`
- `bulk_replace_in_files`
- `run_python_tests`
- `type_check_python`
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

## Optional external tools

Some Monitor features work best when these tools are installed:

- `ripgrep` for repository search
- `redis` for memory-backed features when configured
- `duckdb` for DB-related helpers
- `psql` for PostgreSQL helpers
- `mc` for MinIO/S3-compatible helpers
- `screen` for some terminal workflows on Unix-like systems

## Architecture notes

High-level runtime path:

1. `src/monitor/__main__.py` ensures config assets exist
2. `src/monitor/app.py` loads config, environment globals, logging, and subsystems
3. CLI overrides such as `--model` and `--agent` are applied
4. built-ins, macros, and prompt/wiki context are configured
5. Monitor dispatches to script, server, TUI, or REPL execution

Key source areas:

- `src/monitor/core/` — orchestration, conversation, command routing, tooling
- `src/monitor/lib/` — tools, macros, server, logging, helpers
- `src/monitor/tui/` — terminal UI

## Extending Monitor

See the docs for contributor workflows:

- [`docs/ADD_BUILT_IN.md`](docs/ADD_BUILT_IN.md)
- [`docs/ADD_LLM_TOOL.md`](docs/ADD_LLM_TOOL.md)
- [`docs/MACROS_README.md`](docs/MACROS_README.md)
- [`docs/CORE_README.md`](docs/CORE_README.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Testing

Run the test suite:

```sh
pytest
```

Verbose example:

```sh
PYTHONPATH=. pytest -vv --tb=long -o console_output_style=classic
```

Coverage example:

```sh
PYTHONPATH=. pytest --cov=monitor --cov-report=term-missing --cov-report=html
```

## License

Monitor is distributed under the MIT License. See [`LICENSE`](LICENSE).

## Issues

Please use GitHub issues for bugs and feature requests.
