# Monitor: Modular LLM Command-line Assistant (2024 Edition)

Monitor is a next-generation, modular command-line assistant that seamlessly blends developer productivity tools, natural language interfaces, and intelligent automation directly in your shell or via API. It’s designed for developers, data scientists, and AI enthusiasts who demand power, extensibility, and transparency in daily workflows.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Dual-Mode Operation (CLI & HTTP API)](#dual-mode-operation-cli--http-api)
- [Configuration](#configuration)
- [Usage](#usage)
- [Extending Monitor](#extending-monitor)
- [Registry & Macro System](#registry--macro-system)
- [Logging, Auditing & Structured Logs](#logging-auditing--structured-logs)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Testing](#testing)
- [License & Contact](#license--contact)

---

## Features

- **Unified LLM CLI & API:** Main entrypoint is `app.py`, providing both interactive command-line and HTTP server operation.
- **Programmable Toolchain:** File system, git, ripgrep, code refactoring, database/deployment, and fully user-defined modules.
- **Configurable Context & Automation:** Smart context summarization, dynamic prompt/context rotation, Redis-backed memory.
- **Macro & Registry System:** All commands, tools, and macros integrate via a central registry for consistent, modular extension.
- **Structured Logging & Auditing:** Per-session, audit-friendly, queryable logs with detailed action trail (see [Logging, Auditing & Structured Logs](#logging-auditing--structured-logs)).
- **Extensible Modules:** Hot-pluggable service modules, live registration in core or via Python configuration.
- **Dual-Mode Execution:** Seamlessly run as interactive CLI or launch an HTTP server for API automation/bot integration.
- **Robust Security:** Input validation, error handling, sandboxed execution, and user-confirmed dangerous operations.
- **Persistent Preferences:** Model/user/macro config via YAML and Redis.

---

## Requirements

- **Python** 3.9+  
- **pip** (Python package manager)  
- **Redis** (running for persistent memory/session/history)  
- **Supported OS:** Linux, macOS, Windows (WSL recommended)  
- **Libraries:** See `requirements.txt` for dependencies

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd monitor
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Ensure Redis is running:**
   - Defaults to `localhost:6379`
   - [Download Redis](https://redis.io/download)

4. **Configure as needed:**
   - `app.yaml` for main model/tool/session options
   - `.env` for API keys/tokens/private secrets

---

## Quickstart

```bash
python app.py
```

- Access interactive shell: run commands, issue LLM prompts, trigger macros, inspect logs.
- Use built-in commands (e.g., `:history`, `:preferences`, macro registration, etc.).
- Audit and replay activity via per-session, structured logs.

---

## Dual-Mode Operation (CLI & HTTP API)

Monitor supports both interactive CLI and HTTP API out of the box. Both launch from the same entrypoint (`app.py`):

- **CLI Mode** (default):
    ```bash
    python app.py
    ```
    - Starts an interactive REPL for natural language prompts, shell commands, and tool/macro workflows.
- **HTTP Server Mode**:
    ```bash
    python app.py --server
    ```
    - Launches a RESTful API for LLM chat, automation, and command/macro execution. See the OpenAPI spec or usage in [`ARCHITECTURE.md`](ARCHITECTURE.md).

- **Switch modes at any time** – specify `--server`, `--cli`, or other startup options to choose interface.

---


## Configuration

Monitor uses two primary config files:

- **app.yaml:** Central for models, toolchains, preferences, summarization, registry, and logging/audit.
- **.env:** For secrets (API keys, tokens, environment variables).

For system/module layout, entrypoints, and up-to-date file summaries, see [`ARCHITECTURE.md`](ARCHITECTURE.md).  
Refer there for a top-down overview of core files, extensibility hooks, and launch/operation flow.

---

## Usage

**Main Workflow Steps:**

1. **Startup:** Loads configuration, initializes logging/audit, macro/tool registry, and pluggable modules.
2. **Input Loop:** CLI accepts shell commands, macros, natural language, or pipelines; HTTP API receives JSON command events.
3. **Dispatch & Execution:** All input is parsed through the central registry system—routed to shell, LLM, tool, macro, or plugin as appropriate; rigorous validation and permissions checks enforced.
4. **Persistent & Context Automation:** Session context, macros, and command state maintained and summarized, with structured logs and Redis-backed state/context.
5. **Audit & Log:** All actions, results, errors, and user confirmations are logged in both local files and structured Redis formats for compliance and replay.
6. **Extensible Loop:** Tools/macros/plugins/module hot-reloading (via Python or config changes); command registry updates live.

**Command & Macro Examples**

| Command/Key    | Function                                |
| -------------- | --------------------------------------- |
| `ls, cd, cat`  | Standard file navigation (shell)        |
| `:history`     | View/filter structured session history   |
| `:preferences` | Edit user/session/LLM preferences       |
| `;;;`          | Run multiple commands as pipeline        |
| `F10`          | Voice input                             |
| `<key=macro`   | Define macro or register template command|

- List all available commands/macros with `:commands`.
- Register or modify macros/tools with Python or dynamic command registration (`core/registry`).

---

## Extending Monitor

- Register Python modules in `lib/` or core integrations in `core/`.
- Use the registry API (`core/registry.py`) to add new commands, tool types, macros, or workflow automations in a single place.
- Modules and plugins can be dynamically hot-reloaded and are discoverable via the registry introspection functions.
- See [`ARCHITECTURE.md`](ARCHITECTURE.md) for file relationships, base classes, decorators, plugin wiring, and registration flows.
- All commands, tools, and macros must be registered centrally for discoverability, permissions, and auditing.

---

## Registry & Macro System

- **Central Registry**: Every tool, macro, prompt, and extension is routed via the registry. The registry supports:
    - Live listing and inspection of commands/macros
    - Hot registration/unregistration
    - Modular integration—tools and workflows register via decorators or runtime API.
- Macros, tools, and user-defined workflows share the same registration and dispatch backbone.  
- For advanced use, see referenced module docs in `core/` and `lib/` directories.

---

## Logging, Auditing & Structured Logs

- **Full Structured Logging:** All interaction, tool/macro usage, errors, and LLM/system output are logged per session, with timestamps and actions mirrored to persistent storage.
- **Dual Log Streams:** Logs to both local disk (session logs, error logs) and Redis (for structured, queryable audit).
- **Audit-Ready:** Designed for compliance-intensive or high-stakes environments—includes metadata (user, timestamp, context, registry source, actions).
- **Replay & Query:** Audit logs are machine-readable and can be queried for debugging, compliance, or replay.

---

## Module Documentation

- **Core modules:** See annotated docs in `core/` (central registry, base interfaces, LLM/shell adapters, log managers, permission models).
- **Extension/modules:** Hook or extend behaviors via clear interfaces in `lib/`. Consult inline docstrings and file/module summaries.
- Each module provides usage and extension guidance inline for contributors.

---

## Security

- **Command Safety:** Explicit user confirmation required for destructive or sensitive actions.
- **Sandboxing:** Configurable, pluggable security checks—file/system/network/tool permissions set via policy.
- **Logging:** All access and modifications logged with traceable metadata—audit trails are immutable and queryable.
- **Secrets:** `.env` and external environment are never committed.

---

## Troubleshooting

- **Redis connection refused:** Ensure Redis is started (`localhost:6379` by default).
- **Module import errors:** Verify Python and all pip dependencies (`requirements.txt`) are installed.
- **API/model key issues:** Check `app.yaml` and `.env` for correct paths/credentials.
- **Registry or tool not present:** Use `:commands` and registry APIs to inspect and reload as needed.

### Vim users – Enabling commit message highlighting for :make_commit

When using the `:make_commit` feature, commit messages may be edited in files named *COMMIT_EDITMSG outside `.git/`; add the following to your `~/.vimrc` for gitcommit plugin/syntax support:

    au BufRead,BufNewFile *COMMIT_EDITMSG set filetype=gitcommit

---

## Testing

Run the test suite to verify stability and logic:

```bash
PYTHONPATH=. pytest
```
or for a specific test:
```bash
PYTHONPATH=. pytest tests/<test_file>.py
```
Set `PYTHONPATH=.` to ensure internal imports are correctly resolved during tests.

---

## License & Contact

**License:** MIT  
**Contact:** [support@monitorcli.com](mailto:support@monitorcli.com)

---

**See also:**
- [`ARCHITECTURE.md`](ARCHITECTURE.md) for up-to-date file/module relationships and system overview
- Annotated docs in `core/` and `lib/`
- Structured audit trail and session logs for traceability
