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

### 2. Install Monitor (lightweight core)

The default install is sized for day-to-day repository coding (REPL, providers,
git/search/edit/verify tools, Redis client for optional memory). Heavy extras
are opt-in:

```sh
pip install .
```

For development:

```sh
pip install -e .
pip install -r requirements-dev.txt
```

Optional extras:

| Extra | Install | Provides |
|-------|---------|----------|
| `voice` | `pip install '.[voice]'` | Whisper STT + PyAudio |
| `tts` | `pip install '.[tts]'` | Coqui TTS |
| `chroma` | `pip install '.[chroma]'` | ChromaDB + `chroma-db` CLI |
| `science` | `pip install '.[science]'` | pandas, scikit-learn, joblib, graphviz |
| `database` | `pip install '.[database]'` | DuckDB Python package (CLI still needed on PATH) |
| `network` | `pip install '.[network]'` | Tavily web search |
| `server` | `pip install '.[server]'` | Flask HTTP API (`--server`) |
| `aws` | `pip install '.[aws]'` | boto3 |
| `symbols` | `pip install '.[symbols]'` | tree-sitter outlines/search (`file_outline`, `find_symbol`; Python, JS/TS, Go, Rust, Swift) |
| `all` | `pip install '.[all]'` | Everything above |

Missing extras fail at feature use with an install hint, not at REPL startup.

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

Some features still depend on external tools outside pip:

- `ripgrep`
- `git`
- `redis` (server process when `MEMORY_SERVICES` is enabled)
- `duckdb` CLI (when using the `database` extra / DuckDB tools)
- `ffmpeg` (voice)
- `graphviz` system package (when using the `science` extra for DOT rendering)
- `libmagic`
- `portaudio` (voice)

On macOS with Homebrew:

```sh
brew install pkg-config portaudio libmagic ffmpeg graphviz ripgrep redis duckdb git
brew services start redis
```

## Quick start

1. **Install** the lightweight core (see above).
2. **Configure** a provider key in `~/.config/monitor/.env` (or a project `.env`).
3. **Check** readiness (never prints secret values):

```sh
python -m monitor --check-config
```

4. **Run** the production REPL:

```sh
python -m monitor
# or: monitor
```

5. **Ask for one coding task**, for example: “Show `git status` and summarize
   changed files.” Use `:help` anytime for commands.

First launch seeds packaged defaults into the user config directory **only when
those files are missing** (existing user files are never overwritten). Seeded
files include `config.yaml`, `macros.json`, `preferences.prompt`,
`model_config.json`, command catalogs, and starter directives.

**Production entry point:** `monitor` / `python -m monitor`.  
**Experimental:** `monitor-oop` / `python -m monitor_oop` — not recommended for
day-to-day use; see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Project instruction resolution order: `AGENTS.md`, else `MONITOR.md` /
`build/MONITOR.md`, else packaged/appdir fallback. When `AGENTS.md` is present,
project-local `MONITOR.md` / `MONITOR_CONVENTIONS.md` overrides are skipped.

More detail: [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md),
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Common usage

### Command discovery

```text
:help
:help coding
:help tools
?
```

`:help` (also `/help` or `?`) is the canonical discovery surface. Commands are
grouped by task — coding, repository, session, cost, agent, configuration, and
advanced — with common actions first and short examples for `:tools`,
`:compact`, `:break_chain`, `:reasoning`, cost diagnostics, and session reset.
Search by command name or category (`:help cost`, `:help compact`). Aliases such
as `:model` and `:cc` report their canonical names (`:llm`, `:copy_code`).

Every `:name` built-in also works as `/name`.

### Terminal / internal catalogs

```text
:commands
```

`:commands` lists terminal command entries and internal commands such as `llm<`
and `directive<`. Prefer `:help` for day-to-day built-in discovery; macros and
specialized integrations live under the Advanced section there.

### Built-in commands

Common examples (invoke with `:` or `/`):

- `:tools`
- `:tasks` / `:clear_tasks`
- `:compact` / `:break_chain` / `:reset_history`
- `:reasoning`
- `:llm` (alias `:model`)
- `:cost_debug` / `:dump_metrics`
- `:rg`
- `:agent`
- `:macros`

### Tool profiles (coding-first default)

Monitor advertises a subset of its tool schemas to the model based on the active
**tool profile**. The default is `coding`, which covers the normal repository
loop: read/search/git, task planning, deterministic edits (plus
`modify_source_code` as a fallback), verification, and session memory.

Network, database, and agent tools are withheld from the default profile to save
schema tokens. They become available when you:

- switch profiles explicitly, e.g. `:tools full`
- ask for them in natural language (auto-widen leases the relevant group for a
  few turns)

Useful commands:

```text
:tools
:tools list
:tools catalog
:tools tokens
:tools full
```

`:tools tokens` compares advertised schema size across profiles. Session metrics
from `:dump_metrics` also include the active tool-profile snapshot.

### Live turn activity

During a multi-round-trip turn, Monitor paints a single in-place status line so
a long autonomous loop does not look stalled. While waiting on the model, that
line is the familiar animated spinner with the live activity as its label:

```text
[RT 3 · request sent - processing ⠋ 12s]
```

Between model waits, tool names and running totals appear on the same line
(then clear so tool stdout — diffs, ripgrep hits, file views — prints cleanly):

```text
[RT 3 · run_python_tests · 8.2k input · $0.14 turn]
```

It shows tool names and aggregate counters only — never tool arguments, output,
prompts, or credentials — and adds no model calls. Ripgrep results, edit diffs,
and other tool prints still go to the terminal as before. Activity feedback is
on by default for the interactive REPL and silent for `--script`, piped output,
server, and sub-agent runs. Toggle it at runtime:

```text
:activity          # show current state
:activity off      # quiet
:activity on
:activity toggle
```

Set `LIVE_TURN_FEEDBACK: false` in config to disable by default. Full per-turn
detail remains in the `[SPEND][TURN]` / `[SPEND][TOOL]` log lines.

### Status-line modes

The REPL prompt and TUI info bar share one status line. Control detail with
`:status` or `STATUS_LINE_MODE` in config:

```text
:status              # show current mode
:status coding        # recommended default
:status minimal       # H: + C: cliff % only
:status debug         # all gauges (R:, L:, RT:, cache mix)
```

| Mode | Fields shown |
|------|----------------|
| `minimal` | Message count (`H:`), cliff proximity (`C:`) |
| `coding` | `H: C: U: (~T:$…) F:` |
| `debug` | Full telemetry including rate limit, last request, round-trips, cache mix |

When auto-compaction fires or you stay above the 2x pricing cliff for several
turns, Monitor prints a one-line recovery hint pointing at `:break_chain`,
`:compact`, and `:reset_history`. Use `:help session` for when to use each.

### Deterministic edits and actionable failures

Monitor prefers surgical file tools in this order:

`text_file_create` → `text_file_str_replace_in_file` → `text_file_insert_text_at_line` → `bulk_replace_in_files` → `modify_source_code` (last resort).

When `modify_source_code` is used, a one-line notice marks it as a natural-language
fallback. Failed replaces and similar errors return a short `[category]` message
plus one recovery step (details stay in logs).

To stop models sliding `cat_file` ranges forever looking for text, Monitor caps
reads of the same path per turn (`MAX_PATH_READS_PER_TURN`, default 6) and tells
the model to use `ripgrep_search_tool` instead. Exact-arg repeats are still
blocked by `MAX_REPEATED_TOOL_CALLS`.

`:dump_metrics` includes deterministic vs NL edit counts and read-budget trips.

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
python -m monitor --check-config
python -m monitor --model gpt5
python -m monitor --debug
```

### Reasoning and role-based model behavior

Monitor can adjust reasoning effort during a session when the conversation or tool results call for it.

- A short confirmation such as `Sounds good. Proceed.` can trigger a continuity bump to `medium` reasoning for that turn.
- A tool failure can escalate reasoning to `high` for the rest of the current turn.
- When orchestration is enabled, `--agent` children can use `SUBAGENT_MODEL` / `SUBAGENT_REASONING_EFFORT`, while the orchestrator can use `ORCHESTRATOR_MODEL` / `ORCHESTRATOR_REASONING_EFFORT` transiently during collation turns.
- An explicit `--model` override still wins over role-based defaults.

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

It does not restore the shipped command catalogs or directive starter files.

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

1. `src/monitor/__main__.py` ensures config assets exist (never overwrites)
2. `src/monitor/app.py` loads config, environment globals, logging, and subsystems
3. CLI overrides such as `--model`, `--check-config`, and `--agent` are applied
4. built-ins, macros, and prompt/wiki context are configured
5. Monitor dispatches to script, server, TUI, or REPL execution

Key source areas:

- `src/monitor/core/` — orchestration, conversation, command routing, tooling
- `src/monitor/lib/` — tools, macros, server, logging, helpers
- `src/monitor/tui/` — terminal UI

`src/monitor_oop/` is an **experimental** alternate stack (`monitor-oop`
console script). Prefer `monitor` / `python -m monitor` for production.

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Extending Monitor

See the docs for contributor workflows:

- [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- [`docs/STATUS_LINE.md`](docs/STATUS_LINE.md)
- [`docs/BENCHMARK_USAGE.md`](docs/BENCHMARK_USAGE.md)
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
