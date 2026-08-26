# Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](#requirements)
[![Tests](https://img.shields.io/badge/tests-pytest-informational.svg)](#development-and-testing)

Personal AI coding agent CLI I wrote for my own daily work — REPL + tools +
task planning. It is customized for my workflow, not a general-purpose product.

Monitor is an AI-assisted developer CLI with an interactive REPL, built-in
commands, LLM-callable tools, macros, task planning, and an optional local HTTP
server.

## Overview

Monitor is built for repository-centric development with a mix of shell work,
structured tools, and model assistance.

## Architecture decisions

The repo has one production entry point and a smaller experimental stack.

- **Production:** `monitor` / `python -m monitor`  
  This is the day-to-day CLI. Use it for real work. The full-screen UI
  (`--tui`) is experimental inside this same entry point.
- **Experimental:** `monitor-oop` / `python -m monitor_oop`  
  This is an alternate OOP architecture for design exploration. It is not the
  recommended path for daily use.

Keep production fixes in `src/monitor/`. Use `src/monitor_oop/` only when you
intentionally want to try the alternate stack.

For runtime layout and deeper design notes, see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Why Monitor

- Keep shell workflows and LLM-assisted development in one place
- Use structured tools for git, search, editing, tests, and planning
- Prefer deterministic edits before falling back to natural-language editing
- Scale from interactive REPL usage to scripts, agents, and a local server
  (experimental full-screen TUI via `--tui`)

## Features

- Interactive REPL for shell work and AI-assisted development
- Built-in commands for help, history, tasks, macros, model settings, and
  diagnostics
- LLM-callable tools for git inspection, search, file editing, tests, type
  checking, memory, and todo/task management
- Persistent and ephemeral macros
- Deterministic file editing tools with a natural-language fallback
- Optional local OpenAI-style HTTP server
- Experimental full-screen TUI mode (`--tui`)

## Requirements

- Python 3.10+
- pip
- Some features also rely on external tools such as `git`, `ripgrep`, `redis`,
  `duckdb` CLI, `ffmpeg`, `graphviz`, `libmagic`, and `portaudio`

## Installation

### Clone the repository

```sh
git clone https://github.com/rdegraci/monitor
cd monitor
```

### Install the core package

```sh
pip install .
```

### Development install

```sh
pip install -e .
pip install -r requirements-dev.txt
```

### Optional extras

| Extra | Install | Provides |
|---|---|---|
| `voice` | `pip install '.[voice]'` | Whisper STT + PyAudio |
| `tts` | `pip install '.[tts]'` | Coqui TTS |
| `chroma` | `pip install '.[chroma]'` | ChromaDB + `chroma-db` CLI |
| `science` | `pip install '.[science]'` | pandas, scikit-learn, joblib, graphviz |
| `database` | `pip install '.[database]'` | DuckDB Python package |
| `network` | `pip install '.[network]'` | Tavily web search |
| `server` | `pip install '.[server]'` | Flask HTTP API |
| `aws` | `pip install '.[aws]'` | boto3 |
| `symbols` | `pip install '.[symbols]'` | tree-sitter outlines/search |
| `all` | `pip install '.[all]'` | Everything above |

Missing extras fail at feature use with an install hint rather than at REPL
startup.

### Optional user config

```sh
mkdir -p ~/.config/monitor
cp src/monitor/dot_env_example ~/.config/monitor/.env
$EDITOR ~/.config/monitor/.env
```

Example:

```dotenv
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
XAI_API_KEY=...
```

Monitor also loads a project-local `.env` when present.

## Quick Start

1. Install Monitor.
2. Add a provider API key to `~/.config/monitor/.env` or a project `.env`.
3. Verify configuration:

```sh
python -m monitor --check-config
```

4. Start the CLI:

```sh
python -m monitor
# or: monitor
```

5. Ask for a coding task, for example:

```text
Show git status and summarize changed files.
```

Use `:help` at any time to discover commands.

On first launch, Monitor seeds packaged defaults into the user config directory
only when the target files do not already exist.

## Common Usage

### CLI modes

```sh
python -m monitor
python -m monitor --prompt "Summarize this repository"
python -m monitor --prompt-file prompts/review.txt
python -m monitor --script path/to/script.txt
python -m monitor --server
python -m monitor --agent
python -m monitor --tui   # experimental
```

### Common commands

```text
:help
:tools
:tasks
:clear_tasks
:macros
:llm
:reasoning
:rg
:agent
:dump_metrics
```

Every `:name` built-in also works as `/name`.

### Macros

Show visible macros:

```text
macros
```

Add an ephemeral macro:

```text
<proj=~/projects/monitor
cd {{proj}}
```

For persistent macros, use `:edit_macros` and `:reload_macros`.

### Internal commands

Run shell output through the LLM pipeline:

```text
llm< "git status"
llm< "git diff HEAD~1..HEAD" >llm "Review this diff: ${result}"
```

Use a directive file:

```text
directive< greet.prompt Alice "Acme Corp"
```

### Optional server mode

Monitor can run a local HTTP server for OpenAI-style workflows:

```sh
python -m monitor --server
python -m monitor --server 127.0.0.1 --port 5000
```

This server is intended for local development and single-user workflows. For
internal command behavior and security considerations, see
[`docs/INTERNAL_COMMANDS.md`](docs/INTERNAL_COMMANDS.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Configuration

Monitor uses platform-specific config directories via `appdirs`.

Typical user config locations:

- Linux: `~/.config/monitor`
- macOS: `~/Library/Application Support/monitor`
- Windows: `%APPDATA%/monitor`

Monitor resolves user config files first and falls back to site config where
needed.

Project instruction resolution order:

1. `AGENTS.md`
2. otherwise `MONITOR.md` or `build/MONITOR.md`
3. otherwise packaged/appdir fallback

When `AGENTS.md` is present, project-local `MONITOR.md` and
`MONITOR_CONVENTIONS.md` are skipped.

Logging is configured from the `logging` section in `config.yaml`.

## Documentation

For more detail, see:

- [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- [`docs/STATUS_LINE.md`](docs/STATUS_LINE.md)
- [`docs/BENCHMARK_USAGE.md`](docs/BENCHMARK_USAGE.md)
- [`docs/ADD_BUILT_IN.md`](docs/ADD_BUILT_IN.md)
- [`docs/ADD_LLM_TOOL.md`](docs/ADD_LLM_TOOL.md)
- [`docs/MACROS_README.md`](docs/MACROS_README.md)
- [`docs/CORE_README.md`](docs/CORE_README.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Development and Testing

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
