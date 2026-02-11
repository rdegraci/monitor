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

- Python 3.10+
- pip (latest recommended)
- Supported OS: macOS

## Installation

Monitor provides a console script entry point so it can be installed as a normal Python package (pyproject/setup-based).

1. Clone the repository:
   ```
   git clone <your-repo-url>
   cd <repo-dir>
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

3. Copy the dot_env_example to ~/.config/monitor/.env and edit it
    ```
    mkdir ~/.config
    mkdir ~/.config/monitor
    cp src/monintor/dot_env_example ~/.config/monitor/.env
    vi ~/.config/monitor/.env
    ```

4. Proceed to Platform Setup section below to set up additional MacOS tools:
    - Homebrew - recommended
    - brew install pkg-config portaudio libmagic ffmpeg graphviz ripgrep redis duckdb git  
    - brew services start redis
    - Xcode - recommended

5. Start an interactive Monitor shell from project root or any directory:
    ```
    monitor
    ```
    or
    ```
    python -m monitor
    ```

**Note:** On the first run after installation, Monitor may take several minutes to initialize libraries and large dependencies. This is expected and happens only once.

6. Run the self test macro:
    ```
    {{self_test}}
    ```

7. View the help:
    ```
    :help
    ```

8. Read the additional documentation located in the docs/ directory

---

## Platform setup

Below are explicit, copy-paste ready commands to install common system dependencies required to run Monitor and its optional helper tooling. The primary focus is macOS (Homebrew), with Debian/Ubuntu Linux instructions and two options for Windows (Chocolatey and winget). These commands cover audio support (PortAudio / PyAudio), libmagic (file type detection), ffmpeg (media processing), graphviz (graph rendering), ripgrep (fast search), redis (optional persistence), duckdb (optional DB helper), and build tools where needed.

Note: Run these commands in a terminal/shell with appropriate privileges (sudo on Linux/macOS when shown). For Windows, run the terminal as Administrator for Chocolatey or winget installation actions.

### macOS (Homebrew and Xcode - recommended)

If you do not have Homebrew installed: https://brew.sh/
```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Install developer tools, libraries, and utilities:
```
# Xcode command line tools (build tools)
xcode-select --install

# Update Homebrew
brew update

# Install runtime and build dependencies:
brew install pkg-config portaudio libmagic ffmpeg graphviz ripgrep redis duckdb

# Optionally install other useful tools:
brew install git

# Start Redis (if you want a local Redis for memory)
brew services start redis
```

Python/PyAudio on macOS:
```
# Upgrade packaging tools
python3 -m pip install --upgrade pip setuptools wheel

# Install PyAudio (PortAudio is provided by Homebrew)
python3 -m pip install pyaudio
```

### Debian / Ubuntu (Linux) WARNING - Untested

Update and install core build tools and libraries:
```
# Update package lists
sudo apt update

# Install build tools, Python dev headers, and common libraries
sudo apt install -y build-essential pkg-config python3-dev python3-venv python3-pip \
                    libffi-dev libssl-dev libsndfile1 ffmpeg graphviz ripgrep \
                    redis-server duckdb libmagic1 libmagic-dev portaudio19-dev
```

Start Redis if you installed it:
```
sudo systemctl enable --now redis-server
```

Python / PyAudio on Debian/Ubuntu:
```
# Upgrade packaging tools and install package
python -m pip install --upgrade pip setuptools wheel
pip install pyaudio
```

Notes:
- libmagic: libmagic1 provides runtime; libmagic-dev provides headers for building python-magic where needed.
- portaudio19-dev is required to build PyAudio from source.
- If your distribution provides 'duckdb' in apt, the package above will install it; otherwise install DuckDB via pip (`pip install duckdb`) or download the binary.

### Windows (Chocolatey) WARNING - EXPERIMENTAL

Install Chocolatey (if not already installed). Open an Administrator PowerShell and run:
```
Set-ExecutionPolicy Bypass -Scope Process -Force; `
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; `
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

Install tooling and dependencies via Chocolatey:
```
# Install core tools and libraries
choco install -y python git ffmpeg graphviz ripgrep duckdb

# Redis (Windows port; for local testing)
choco install -y redis-64

# Visual Studio Build Tools (for compiling Python wheels)
choco install -y visualstudio2022buildtools --package-parameters "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

# Optional: install pkg-config-lite for some native builds
choco install -y pkgconfiglite
```

Python / PyAudio on Windows (pipwin recommended for prebuilt wheels):
```
# Ensure pip is upgraded
python -m pip install --upgrade pip setuptools wheel

# Install pipwin (helps install PyAudio binary wheels on Windows)
python -m pip install pipwin
python -m pipwin install pyaudio
```

If you prefer to install PyAudio from a wheel manually, visit Christoph Gohlke's Windows binaries (https://www.lfd.uci.edu/~gohlke/pythonlibs/) and download the appropriate PyAudio wheel for your Python version and architecture, then install with:
```
python -m pip install path\to\PyAudio‑<version>.whl
```

If you installed Redis via Chocolatey, start the service (run as Administrator):
```
# Redis installed via chocolatey often installs as a service; start it:
net start Redis
```

### Windows (winget)

If you prefer winget (Windows Package Manager), open an elevated Command Prompt or PowerShell:

Install core tools:
```
# Install Python (if needed)
winget install -e --id Python.Python.3

# Install Git
winget install -e --id Git.Git

# FFmpeg
winget install -e --id ffmpeg.ffmpeg

# Graphviz
winget install -e --id Graphviz.Graphviz

# ripgrep
winget install -e --id BurntSushi.ripgrep

# DuckDB (community package if available)
winget install -e --id DuckDB.DuckDB

# Visual Studio Build Tools 2022
winget install -e --id Microsoft.VisualStudio.2022.BuildTools
```

For Redis on Windows via winget, there may not be an official package; prefer Chocolatey for Redis on Windows, or run Redis in WSL/Docker for development.

After tool installation, use pip/pipwin for PyAudio as shown in the Chocolatey section.

### Notes and recommendations

- Prefer native package managers (Homebrew on macOS, apt on Debian/Ubuntu) for system libraries and long-running services like Redis.
- On Windows, pipwin simplifies installing PyAudio; Visual Studio Build Tools are required if you must compile wheels from source.
- If you encounter issues with libmagic on Windows, use the `python-magic-bin` or `python-magic` packages that include Windows-compatible binaries, or install the file utility via MSYS2/WSL.
- DuckDB is available both as a system package and a Python package (`pip install duckdb`). Use the Python package if you do not need the system CLI.
- If you use Docker/WSL on Windows, you can prefer installing Linux versions of these dependencies inside your Linux container/VM for parity.

If you need help tailoring these commands to your exact OS version or environment (e.g., corporate Windows images, Apple Silicon macs, or minimal Linux containers), consult your platform package manager documentation or ask for platform-specific adjustments.

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
  When run as a module, Monitor copies default configuration files into the user config directory (see OS-specific paths below) if they do not already exist. This is a one-time initialization step unless you explicitly reset the configuration.

The module start-up and CLI behavior are implemented in __main__.py and src/monitor/app.py. The CLI supports flags (described below) and the server mode starts a local Flask-based HTTP server.

### User config directory paths (appdirs)

Monitor uses platform-appropriate user config directories (via appdirs-style conventions):

- macOS: ~/Library/Application Support/monitor
- Linux: ~/.config/monitor
- Windows: %APPDATA%/monitor (e.g., C:\Users\<User>\AppData\Roaming\monitor)

## Default config files copied to user config dir

Running `python -m monitor` (or the console script on first run) will ensure the user config directory exists and will copy default configuration files there if they are missing:

- config.yaml
- macros.json
- preferences.prompt
- model_config.json

Examples:
- (Linux example)
  - ~/.config/monitor/config.yaml
  - ~/.config/monitor/macros.json
  - ~/.config/monitor/preferences.prompt
  - ~/.config/monitor/model_config.json
- (macOS example)
  - ~/Library/Application Support/monitor/config.yaml
  - ~/Library/Application Support/monitor/macros.json
  - ~/Library/Application Support/monitor/preferences.prompt
  - ~/Library/Application Support/monitor/model_config.json
- (Windows example)
  - %APPDATA%/monitor/config.yaml
  - %APPDATA%/monitor/macros.json
  - %APPDATA%/monitor/preferences.prompt
  - %APPDATA%/monitor/model_config.json

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
  - Reset user configuration files in the user config directory (see OS-specific paths above) back to the packaged defaults. Existing files are backed up before being replaced.

- --force
  - Non-interactive mode for operations that would normally prompt (for example, `--reset-config`). Implies yes to confirmations and will perform backups and replacements without prompting.

Behavior details:
- When `--reset-config` is run, any existing file that would be replaced is moved to a backup file with a timestamp suffix: originalfilename.bak_YYYYmmddTHHMMSS (UTC). For example: `config.yaml.bak_20250810T153045`.
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

### Concurrency & Single-User Mode

- Server mode is single-user and processes one request at a time. All incoming requests are serialized; no concurrent request handling is performed.
- Even when bound to 0.0.0.0 or placed behind a reverse proxy, Monitor’s server mode will still handle only one request at a time.
- Intended for local development, testing, and single-user workflows. Not suitable for production or multi-tenant deployments.
- Recommendation: Prefer binding to localhost (127.0.0.1). If you choose to expose the server beyond localhost, ensure you add appropriate network security controls, authentication, TLS/HTTPS termination, rate limiting, and isolation. Use a production-grade serving stack if you require concurrency or multi-user access.

### OpenAI-compatible API endpoints

Monitor exposes a minimal, OpenAI-compatible REST surface for simple integrations.

- Endpoints:
  - GET /v1/models
    - Returns a models list compatible with OpenAI’s schema. The configured model is included; additional metadata may be limited.
  - POST /v1/chat/completions
    - Accepts OpenAI Chat Completions JSON (messages[], model, stream, temperature, etc.). Unsupported fields are safely ignored.

- Authentication:
  - Set MONITOR_SERVER_API_KEY in the server environment to require a header: Authorization: Bearer <MONITOR_SERVER_API_KEY>.
  - If MONITOR_SERVER_API_KEY is unset, no authentication is enforced (not recommended for non-local use).

- Behavior and mapping:
  - Messages are reduced to the latest user message by default and routed through Monitor’s internalize_command pipeline (not direct query()).
  - The request’s "model" field is ignored; Monitor always uses its configured model for processing. Use the CLI flag --model at startup to change it for that process.
  - If stream=true, Monitor simulates streaming by emitting incremental deltas in an OpenAI-compatible shape, chunking the final response into multiple partial updates. If stream=false (default), a single non-streaming response is returned.

- Limitations:
  - Single-user, one request at a time (matches Server Mode concurrency).
  - Tool/function calling is not implemented; extra fields are ignored.

## Logging and Conversation Storage

- Application logs and conversation logs are stored under the user config directory (see OS-specific paths above):
  - (Linux example) ~/.config/monitor/logs/
  - (macOS example) ~/Library/Application Support/monitor/logs/
  - (Windows example) %APPDATA%/monitor/logs/
- Logs include CLI/API invocations, LLM prompts and completions, macro executions, and other audit information.
- Configure alternate log directories via `config.yaml` in your user config directory.

Defaults and naming conventions:
- Default log directory: appdirs.user_config_dir('monitor')/logs — Monitor uses the platform-appropriate user config directory plus "logs" by default (see examples above).
- Default app log filename: app.log. The logging system may inject the process id (PID) into the filename when needed (for example: app.log or app-12345.log) to avoid collisions when multiple instances run.
- Config backup filenames: backups use UTC timestamps with a 'T' separator and a trailing 'Z' in the suffix. Example backup name: originalfilename.bak_20250810T153045Z (UTC).

## Environment (.env) loading order

Monitor supports loading environment variables from .env files. The order is:

1. Project-level `.env` in the current working directory (if present).
2. User-level `.env` in the user config directory (if present) — values here override the project-level values.
   - (Linux example) ~/.config/monitor/.env
   - (macOS example) ~/Library/Application Support/monitor/.env OR ~/.config/monitor/.env
   - (Windows example) %APPDATA%/monitor/.env

This ordering allows project-specific overrides while enabling persistent credentials or defaults in the user config directory.

## model_config.json loading and validation

- Monitor loads `model_config.json` from the packaged defaults and from the user config directory (user override).
  - (Linux example) ~/.config/monitor/model_config.json
  - (macOS example) ~/Library/Application Support/monitor/model_config.json
  - (Windows example) %APPDATA%/monitor/model_config.json
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
  sudo apt install redis-server
  redis-server
  ```
- Windows:
  Use WSL, Docker, or official binaries: https://redis.io/docs/install/install-redis/

### DuckDB CLI (optional)

Used by database helpers for running DuckDB queries (db_storage.execute_duckdb).

- macOS (Homebrew):
  ```
  brew install duckdb
  ```
- Linux (apt):
  ```
  sudo apt install duckdb
  ```
- Windows:
  Download binaries from https://duckdb.org/ or use Chocolatey/Scoop.

### PostgreSQL client (psql) (optional)

Used by database helpers to run SQL via psql (db_storage.execute_psql).

- macOS (Homebrew):
  ```
  brew install postgresql
  # or: brew install libpq && echo 'export PATH="$(brew --prefix libpq)/bin:$PATH"' >> ~/.zshrc
  ```
- Linux (apt):
  ```
  sudo apt install postgresql-client
  ```
- Windows:
  Install PostgreSQL from https://www.postgresql.org/download/ (includes psql).

### MinIO Client (mc) (optional)

Used by storage helpers to interact with S3-compatible endpoints (db_storage.execute_mc).

- macOS (Homebrew):
  ```
  brew install minio-mc
  ```
- Linux/Windows:
  Follow official instructions: https://min.io/docs/minio/linux/reference/minio-mc.html

### GNU screen (optional; Linux/Unix)

Used by terminal_commands to launch commands in detached terminal sessions.

- macOS (Homebrew):
  ```
  brew install screen
  ```
- Linux (apt):
  ```
  sudo apt install screen
  ```
- Windows:
  Not available natively; consider WSL.

### macOS AppleScript (osascript)

Used by terminal_commands to open Terminal and run commands on macOS.

- macOS: Provided by the OS ("osascript"). No installation needed.
- Other platforms: Not applicable.

### Unix utilities: diff, file, patch

Used by OS helpers for file diffs, MIME/type checks, and applying patches.

- macOS: Provided by the OS. Optionally:
  ```
  brew install diffutils file-formula gnu-tar
  brew install patch
  ```
- Linux (apt):
  ```
  sudo apt install diffutils file patch
  ```
- Windows:
  Use WSL or install via Git Bash/MSYS2 where available.

### Audio playback utilities (afplay/aplay)

Used by text-to-speech helper for simple WAV playback.

- macOS: "afplay" is provided by the OS.
- Linux (apt):
  ```
  sudo apt install alsa-utils  # provides aplay
  ```
- Windows: Uses winsound via Python stdlib (no extra install).

### Editors (vim/nano/vi)

Used by macros editor command to open the macros file when $EDITOR is not set.

- macOS (Homebrew):
  ```
  brew install vim nano
  ```
- Linux (apt):
  ```
  sudo apt install vim nano
  ```
- Windows:
  Use a terminal editor available in your environment (e.g., Vim via Git Bash) or set EDITOR to your preferred GUI editor.

Note: Monitor no longer documents internal TTLs for conversation memory in the README; refer to runtime configuration in `config.yaml` for your environment's retention behavior.

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

## Configuration and Usage Basics

Monitor loads configuration from the user config directory (see OS-specific paths above). This directory is populated on first run when using `python -m monitor` or the console script. Persistent settings are read from `config.yaml`, and secrets may be loaded from `.env` in the user config directory as described in the "Environment (.env) loading order" section.

Example `config.yaml` snippet (Linux example shown; adjust paths for your OS):
```yaml
model:
  provider: openai
  model: gpt-4
registry:
  path: ~/.monitor/registry
logs:
  path: ~/.config/monitor/logs
```

Place your `.env` values in the user config directory `.env` for persistent secrets:
- (Linux example)
```
# ~/.config/monitor/.env
OPENAI_API_KEY=<key>
ANTHROPIC_API_KEY=<key>
XAI_API_KEY=<key>
```
- (macOS example)
```
# ~/Library/Application Support/monitor/.env
OPENAI_API_KEY=<key>
ANTHROPIC_API_KEY=<key>
XAI_API_KEY=<key>
```
- (Windows example)
```
# %APPDATA%/monitor/.env
OPENAI_API_KEY=<key>
ANTHROPIC_API_KEY=<key>
XAI_API_KEY=<key>
```

Flags and environment variables may override YAML settings at launch. Use `--model` to override only the model selection for the running process.

Usage modes:
- Interactive shell: Type commands, ask for code change suggestions, or interact directly with git context.
- LLM direct queries: "How do I optimize this function?" or "Review last commit" and receive in-place code modifications.
- Macros: Compose batch automations via reusable macro scripts.

See `docs/ARCHITECTURE.md` and `docs/CORE_README.md` for full configuration options and advanced usage.

## Extending Monitor

- **Custom Macros:** Write macros in YAML or JSON and place them under the macros directory or user registry (macros file resides in the user config directory). See `docs/MACROS_README.md` for more information.
- **Tool System:** Develop and register LLM tools for custom API/data access. See `docs/ADD_LLM_TOOL.md` for more information.
- **Command System:** Develop and register built-in commands. See `docs/ADD_BUILT_IN.md`

See developer docs in `docs/CORE_README.md` and `docs/ARCHITECTURE.md` for examples and extension points.

## Logging and Auditing

All Monitor operations are logged to the local registry (when configured) and file-based logs. You can inspect, export, and replay previous session logs for compliance or debugging. Logs include:

- CLI/API invocations
- LLM prompts, completions, code actions
- Shell and code executions, results, and errors
- Macro executions and workflow traces

Default logs location (under the user config directory):
- (Linux example)
```
~/.config/monitor/logs/
```
- (macOS example)
```
~/Library/Application Support/monitor/logs/
```
- (Windows example)
```
%APPDATA%/monitor/logs/
```

Specify alternate log directories via `config.yaml` in your user config directory.

## Troubleshooting

- **Redis connection issues:** Ensure `redis-server` is running and accessible if you have enabled Redis in your configuration.
- **Invalid config.yaml or missing .env:** Validate your config files and environment variable values. Use `--reset-config` to restore defaults if needed.
- **Unsupported OS / Python version:** Use Python 3.10 or later on supported platforms.
- **LLM API errors:** Confirm API keys and correct model provider setup in `model_config.json`, `config.yaml`, or environment variables located in the user config directory:
  - (Linux example) ~/.config/monitor/
  - (macOS example) ~/Library/Application Support/monitor/
  - (Windows example) %APPDATA%/monitor/
- **Permissions or sandboxing errors:** Check directory/file permissions and security configuration in `config.yaml`.

For more, see `docs/CORE_README.md` and `docs/ARCHITECTURE.md`.

## Testing

Run tests with:
```
pytest

or

PYTHONPATH=. pytest -vv --tb=long -o console_output_style=classic
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

For code test coverage:
```
PYTHONPATH=. pytest --cov=monitor --cov-report=term-missing --cov-report=html
```

See test documentation in `docs/CORE_README.md` and `docs/ARCHITECTURE.md`.

## License

Monitor is open source, distributed under the MIT License. See `LICENSE` for full terms.

## Contact

For issues or feature requests, please file an issue on GitHub:  
https://github.com/rdegraci/monitor

For architectural details and advanced extension, consult `docs/ARCHITECTURE.md` and `docs/CORE_README.md`.
