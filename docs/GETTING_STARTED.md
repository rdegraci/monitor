# Getting Started: Becoming Productive With Monitor

Monitor is an AI-assisted developer CLI optimized for day-to-day repository
coding: interactive REPL, built-in commands, LLM-callable tools, macros, task
planning, optional TUI, and an optional local HTTP server.

**Production entry point:** `monitor` / `python -m monitor`  
**Experimental (not for primary use):** `monitor-oop` / `python -m monitor_oop`

## Install and configure

```sh
pip install .                    # lightweight core
# or: pip install -e . && pip install -r requirements-dev.txt

mkdir -p ~/.config/monitor
cp src/monitor/dot_env_example ~/.config/monitor/.env
# Edit ~/.config/monitor/.env — set at least one provider key
```

Validate without printing secrets:

```sh
python -m monitor --check-config
```

Optional extras (`voice`, `tts`, `chroma`, `science`, `database`, `network`,
`server`, `aws`, `symbols`, `all`) are documented in the README. Missing extras fail at
feature use with an install hint, not at REPL startup.

## First coding session

```sh
python -m monitor
```

You should see `Monitor ready!`. Then:

1. Run `:help` (also `/help` or `?`) — task-grouped command discovery.
2. Ask the model to inspect the repo, e.g. “Show git status and summarize changes.”
3. Prefer `:help coding` / `:help session` when stuck.

Useful startup flags:

```sh
python -m monitor --version
python -m monitor --models
python -m monitor --check-config
python -m monitor --model gpt5
python -m monitor --debug
python -m monitor --script path/to/script.txt
python -m monitor --tui
python -m monitor --server 127.0.0.1 --port 5000
python -m monitor --agent
```

### First-run seeding

On start, `src/monitor/__main__.py` copies packaged defaults into the user
config directory **only if missing**. Existing user files are never overwritten.

Seeded files include:

- `config.yaml`
- `macros.json`
- `preferences.prompt`
- `model_config.json`
- `interactive_commands.json` / `non_interactive_commands.json`
- `directives/echo.prompt` / `directives/greet.prompt`

Logs typically land under `~/.config/monitor/logs` on Unix-like setups.

## Command discovery

Prefer `:help` over memorizing long lists:

```text
:help
:help coding
:help session
:help cost
:help tools
?
```

Every `:name` built-in also works as `/name`. Aliases report their canonical
names (`:model` → `:llm`, `:cc` → `:copy_code`).

`:commands` lists terminal/internal catalog entries (`llm<`, `directive<`).
Day-to-day built-in discovery belongs in `:help`.

Common built-ins:

| Area | Examples |
|------|----------|
| Tools / profile | `:tools`, `:tools full`, `:tools tokens` |
| Session | `:compact`, `:break_chain`, `:reset_history`, `:tasks` |
| Cost / debug | `:cost_debug`, `:dump_metrics`, `:status`, `:activity` |
| Model | `:llm`, `:reasoning` |
| Search | `:rg`, `:symbols` |

## Tool profile (coding-first)

The default **tool profile** is `coding`: read/search/git, tasks, deterministic
edits (with `modify_source_code` as last-resort fallback), verification, and
session memory. Network, database, and agent tools are withheld until you
`:tools full` or ask for them (auto-widen leases them for a few turns).

```text
:tools
:tools list
:tools catalog
:tools tokens
:tools full
```

## On-demand code symbols

Install the optional parsers:

```sh
pip install '.[symbols]'
```

The LLM can then call these automatically when structure is needed:

- `find_symbol(query, path=".", kind="all")` locates definitions across a repo.
- `file_outline(path, kind="all")` outlines one file.

Supported languages: Python, JavaScript, TypeScript/TSX, Go, Rust, and Swift.
The tools are in `core_read` and the default `coding` profile, but return no
symbol data unless called. Use ripgrep for textual references, usages, strings,
or arbitrary content.

Diagnostics:

```text
:symbols
:symbols langs
:symbols cache
```

Symbol calls are capped per turn (`MAX_SYMBOL_QUERIES_PER_TURN`, default 12).
The cache is stored in the platform user-cache directory, never in the repo.
`:dump_metrics` includes payload-free symbol call/cache/result counters.

## Live feedback and status line

During multi-round turns, a single in-place activity line shows round-trip,
tool name, and spend counters (never args/prompts/secrets). Toggle with
`:activity` / `LIVE_TURN_FEEDBACK`.

The REPL/TUI status line has modes via `:status` or `STATUS_LINE_MODE`
(default `coding`). See [`STATUS_LINE.md`](STATUS_LINE.md).

## Deterministic edits

Prefer surgical tools in this order:

`text_file_create` → `text_file_str_replace_in_file` →
`text_file_insert_text_at_line` → `bulk_replace_in_files` →
`modify_source_code` (NL fallback, last).

Failed tools return a short `[category]` message plus one recovery step.
Repeated `cat_file` sliding on the same path is capped
(`MAX_PATH_READS_PER_TURN`, default 6).

## Session recovery

When context pressure or cliff warnings appear:

| Command | Use when |
|---------|----------|
| `:break_chain` | Keep history but drop the 2× cliff / chain pressure |
| `:compact` | Summarize older turns into a smaller retained history |
| `:reset_history` | Start a fresh task with a clean history |

See `:help session`.

## Macros and internals

Persistent macros: `macros.json`. Ephemeral: `<name=value` then `{{name}}`.
Tcl in macros is trusted executable code — treat carefully.

Internal pipelines:

```text
llm< "git status"
directive< greet.prompt Alice
```

## Modes beyond the REPL

| Mode | Flag |
|------|------|
| TUI | `--tui` |
| Script | `--script path.txt` |
| Server | `--server [host] --port N` |
| Agent behavior | `--agent` (modifier, not a separate front end) |

Server endpoints: `POST /cli`, `GET /v1/models`, `POST /v1/chat/completions`.
Protect non-localhost binds; use `MONITOR_SERVER_API_KEY` for `/v1/*` Bearer auth.

Agent tools (`agent_create`, …) need the agent tool group (e.g. `:tools full` or
orchestration config). Wiki built-ins: `:wiki_init`, `:wiki_lint`, `:wiki_fix`.

## Quick cheat sheet

| Action | Example |
|--------|---------|
| Check config | `python -m monitor --check-config` |
| Start REPL | `python -m monitor` |
| Discover commands | `:help` |
| Tool profile | `:tools` / `:tools full` |
| Status detail | `:status coding` |
| Activity line | `:activity on` |
| Task plan | `:tasks` / `:clear_tasks` |
| Recover context | `:break_chain` / `:compact` / `:reset_history` |
| Symbol parsers | `pip install '.[symbols]'` then `:symbols` / `:symbols langs` |

## Next docs

- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — install, auth, context, extras
- [`STATUS_LINE.md`](STATUS_LINE.md) — field and mode reference
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — runtime layout (includes experimental OOP path)
- [`CORE_README.md`](CORE_README.md) — `core/` module map
- README — install extras and full feature inventory
