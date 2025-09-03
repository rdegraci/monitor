# Monitor

Monitor is a modular Large Language Model (LLM) developer assistant designed for robust command-line interface (CLI) and API-driven workflows. It provides advanced shell, code, and git integration; macro command composition; a registry system for plugin discovery; persistent logging and audit trails; secure extensibility; and systematic configuration for critical and large-scale developer environments.

Monitor is ideal for software professionals who need a safe, auditable, and scriptable LLM tool that can be tailored to sophisticated CI/CD, devops, and research/automation scenarios.

## Key Features

- **Structured LLM Terminal:** Intelligent command-line shell with LLM integration and secure sandboxing of code or shell execution.
- **Code Assistant:** Code generation, refactoring, and documentation across multiple languages/tools for developers.
- **Git Support:** Context-aware git toolset for code review, commit assistance, and repository analytics.
- **Macros:** Compose multi-step automations and chained LLM actions (workflows) using macros, making complex tasks repeatable and safe.
- **Registry System:** Fully auditable plugin and macro registry—discover, share, and govern tools and automations.
- **Audit & Logging:** Every action, prompt, and result is logged for transparency, compliance, and reproducibility.
- **Security:** Code execution controls, sandboxing, environment whitelisting, and robust user-supplied configuration.
- **Extensible:** Easily add custom macros, LLM tools, built-in functions, or integrate with external systems.
- **Modern CLI & API:** Use interactively via terminal, run as a local HTTP server for API-driven workflows, or embed in scripts and automation.
- **Cross-platform:** Runs on Linux, macOS, Windows.

## Requirements

- Python 3.9+
- pip (latest recommended)
- Supported OS: Linux, macOS, Windows 10/11

## Installation

Monitor provides a console script entry point so it can be installed as a normal Python package (pyproject/setup-based).

1. Clone the repository:
   ```
   git clone https://github.com/YOUR_ORG/monitor3.git
   cd monitor3
   ```

2. Install the package (regular or editable):
   ```
   pip install .
   ```
   or for development:
   ```
   pip install -e .
   ```
   The installation registers a `monitor` console script (via pyproject/setup) so you can launch Monitor directly from your shell.

---
**Note:** On the first run after installation, Monitor may take several minutes to initialize libraries and large dependencies. This is expected and happens only once. The app will display a warning message the first time to notify you of this.
---

## How Monitor is run

You can run Monitor in two main ways:

- As an installed console script:
  ```
  monitor
  ```
  or with flags:
  ```
  monitor --server 0.0.0.0 --port 8080
  monitor --model gpt-4
  ```

- As a Python module (module invocation):
  ```
  python -m monitor
  ```
  When run as a module, Monitor copies default configuration files into the user configuration directory (~/.config/monitor) if they do not already exist. This is a one-time initialization step unless you explicitly reset the configuration.

The module start-up and CLI behavior are implemented in __main__.py and src/monitor/app.py. The CLI supports flags (described below) and the server mode starts a local Flask-based HTTP server.

## Default config files copied to user config dir

Running `python -m monitor` (or the console script on first run) will ensure a user config directory exists and will copy default configuration files there if they are missing:

- ~/.config/monitor/app.yaml
- ~/.config/monitor/macros.json
- ~/.config/monitor/preferences.prompt
- ~/.config/monitor/model_config.json

If you need to reset these files to defaults, see the "Reset configuration" section below.

## CLI Flags and Behavior

Monitor supports the following command-line flags:

- --server [host]
  - Start server mode. Optional host argument sets the binding host (default: 127.0.0.1).
  - Example: `monitor --server` (binds to 127.0.0.1) or `monitor --server 0.0.0.0` (bind to all interfaces).

- --port N
  - Specify server port (default: 5000). Example: `monitor --server --port 8080`.

- --model NAME
  - Override the configured model selection for this run. This prints the effective model selection on startup and uses it for LLM interactions during the session.

- --reset-config
  - Reset user configuration files in ~/.config/monitor back to the packaged defaults. Existing files are backed up before being replaced.

- --force
  - Non-interactive mode for operations that would normally prompt (for example, `--reset-config`). Implies yes to confirmations and will perform backups and replacements without prompting.

Behavior details:
- When `--reset-config` is run, any existing file that would be replaced is moved to a backup file with a timestamp suffix: originalfilename.bak_YYYYmmddTHHMMSS (UTC). For example: `app.yaml.bak_20250810T153045`.
- Using `--force` will skip interactive confirmation prompts and proceed with backup and replacement.
- `--model` overrides the model selection from configuration files for the lifetime of that process and prints the effective model selection during startup.

## Server Mode

- The server mode runs a lightweight Flask HTTP server (implemented in src/monitor/app.py).
- Default host: 127.0.0.1
- Default port: 5000
- Example to run on all interfaces, port 8080:
  ```
  monitor --server 0.0.0.0 --port 8080
  ```

## Logging and Conversation Storage

- Application logs and conversation logs are stored under the user config directory:
  - ~/.config/monitor/logs/
- Logs include CLI/API invocations, LLM prompts and completions, macro executions, and other audit information.
- Configure alternate log directories via `~/.config/monitor/app.yaml`.

## Environment (.env) loading order

Monitor supports loading environment variables from .env files. The order is:

1. Project-level `.env` in the current working directory (if present).
2. User-level `~/.config/monitor/.env` (if present) — values here override the project-level values.

This ordering allows project-specific overrides while enabling persistent credentials or defaults in the user config directory.

## model_config.json loading and validation

- Monitor loads `model_config.json` from the packaged defaults and from `~/.config/monitor/model_config.json` (user override).
- The file is parsed and validated at startup. The validator ensures the presence of the minimum required keys:
  - `provider` (e.g., "openai", "anthropic", "xai")
  - `model` (provider-specific model identifier)
- Additional provider-specific configuration may be required (for example, API-specific parameters); missing required keys will cause Monitor to fail startup with a clear error message indicating which keys are missing.
- Use `--model` to temporarily override the effective model selection without changing saved configuration.

## Optional Tools

The following external tools are optional for running Monitor, but are highly recommended for advanced features, improved performance, production, or development scenarios. Monitor can run basic commands without these tools, but more advanced setups and workflows will benefit from having them available.

### ripgrep

Installing ripgrep enables the `:ripgrep <search>` command in Monitor. This command allows you to search for a string in your codebase, and Monitor will analyze how that string is used throughout your project.

- macOS (Homebrew):
  ```
  brew install ripgrep
  ```
- Linux (apt):
  ```
  sudo apt install ripgrep
  ```
- Windows:
  Download from https://github.com/BurntSushi/ripgrep/releases and add to your PATH.

### Redis (optional)

Redis is optional and used when configured as a persistence or registry backend for advanced features (session memory, registry syncing). Monitor can operate without Redis, but enabling it provides persistent storage across restarts and centralized registry features.

- macOS (Homebrew):
  ```
  brew install redis
  redis-server
  ```
- Linux (apt):
  ```
  sudo apt install redis
  redis-server
  ```
- Windows:
  Use WSL, Docker, or official binaries: https://redis.io/docs/install/install-redis/

Note: Monitor no longer documents internal TTLs for conversation memory in the README; refer to runtime configuration in `app.yaml` for your environment's retention behavior.

## Quickstart

Start an interactive Monitor shell from project root or any directory:
```
monitor
```
or
```
python -m monitor
```

Start server mode (default host 127.0.0.1 and port 5000):
```
monitor --server
```

Start server on all interfaces on port 8080:
```
monitor --server 0.0.0.0 --port 8080
```

Override model selection for a single run:
```
monitor --model gpt-4
```

Reset user configuration (interactive):
```
monitor --reset-config
```

Reset user configuration non-interactively (backups created, no prompts):
```
monitor --reset-config --force
```

Run a saved macro:
```
monitor --macro deploy
```

Send a shell command for LLM-assisted explanation:
```
monitor --command "explain: ls -l"
```

See `src/monitor/README.md` for developer-focused examples and integration notes.

## Configuration and Usage Basics

Monitor loads configuration from the user config directory `~/.config/monitor` (populated on first run when using `python -m monitor` or the console script). Persistent settings are read from `app.yaml`, and secrets may be loaded from `~/.config/monitor/.env` as described in the "Environment (.env) loading order" section.

Example `app.yaml` snippet:
```yaml
model:
  provider: openai
  model: gpt-4
registry:
  path: ~/.monitor/registry
logs:
  path: ~/.config/monitor/logs
```

Place your `.env` values in `~/.config/monitor/.env` for persistent secrets:
```
# ~/.config/monitor/.env
OPENAI_API_KEY=<key>
ANTHROPIC_API_KEY=<key>
XAI_API_KEY=<key>
```

Flags and environment variables may override YAML settings at launch. Use `--model` to override only the model selection for the running process.

Usage modes:
- Interactive shell: Type commands, ask for code change suggestions, or interact directly with git context.
- LLM direct queries: "How do I optimize this function?" or "Review last commit" and receive in-place code modifications.
- Macros: Compose batch automations via reusable macro scripts.

See `docs/ARCHITECTURE.md` or `src/monitor/README.md` for full configuration options and advanced usage.

## Extending Monitor

- **Custom Macros:** Write macros in YAML or JSON and place them under the macros directory or user registry (`~/.config/monitor/macros.json`). See `docs/MACROS_README.md` for more information.
- **Tool System:** Develop and register LLM tools for custom API/data access. See `docs/ADD_LLM_TOOL.md` for more information.
- **Command System:** Develop and register built-in commands. See `docs/ADD_BUILT_IN.md`

See developer docs in `src/monitor/README.md` for examples and extension points.

## Logging and Auditing

All Monitor operations are logged to the local registry (when configured) and file-based logs. You can inspect, export, and replay previous session logs for compliance or debugging. Logs include:

- CLI/API invocations
- LLM prompts, completions, code actions
- Shell and code executions, results, and errors
- Macro executions and workflow traces

Default logs location:
```
~/.config/monitor/logs/
```
Specify alternate log directories via `~/.config/monitor/app.yaml`.

## Troubleshooting

- **Redis connection issues:** Ensure `redis-server` is running and accessible if you have enabled Redis in your configuration.
- **Invalid app.yaml or missing .env:** Validate your config files and environment variable values. Use `--reset-config` to restore defaults if needed.
- **Unsupported OS / Python version:** Use Python 3.9 or later on supported platforms.
- **LLM API errors:** Confirm API keys and correct model provider setup in `~/.config/monitor/model_config.json`, `app.yaml`, or environment variables.
- **Permissions or sandboxing errors:** Check directory/file permissions and security configuration in `app.yaml`.

For more, see `src/monitor/README.md`.

## Testing

Run tests with:
```
pytest
```
To run all integration and system tests:
```
pytest tests/
```
For local CLI/dev loop, use "editable" install:
```
pip install -e .
monitor
```
See test documentation in `src/monitor/README.md`.

## License

Monitor is open source, distributed under the MIT License. See `LICENSE` for full terms.

## Contact

For issues or feature requests, please file an issue on GitHub:  
https://github.com/YOUR_ORG/monitor3

For architectural details and advanced extension, consult `docs/ARCHITECTURE.md` and `src/monitor/README.md`.
