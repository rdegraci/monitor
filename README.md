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
- **Extensible:** Easily add custom macros, tool plugins, or integrate with external systems.
- **Modern CLI & API:** Use interactively via terminal, run as a local server for API-driven workflows, or embed in scripts and automation.
- **Cross-platform:** Runs on Linux, macOS, Windows.

## Requirements

- Python 3.9+
- pip (latest recommended)
- Supported OS: Linux, macOS, Windows 10/11

## Optional Tools

The following external tools are optional for running Monitor, but are highly recommended for advanced features, improved performance, production, or development scenarios. Monitor can run basic commands without these tools, but more advanced setups and workflows will benefit from having them available.

### ripgrep

_Installing ripgrep enables the `:ripgrep <search>` command in Monitor. This command allows you to search for a string in your codebase, and Monitor will analyze how that string is used throughout your project._

_ripgrep_ enables fast source code and text searching for advanced code analysis and fuzzy context search in Monitor. It is not strictly required, but using ripgrep improves search speed and capability within codebases.

- **macOS (using Homebrew):**
  ```
  brew install ripgrep
  ```
- **Linux (using apt):**
  ```
  sudo apt install ripgrep
  ```
- **Windows:**
  Download from [https://github.com/BurntSushi/ripgrep/releases](https://github.com/BurntSushi/ripgrep/releases) and add to your PATH.

### Redis on localhost

_Redis_ enables Monitor's memory persistence layer, which is used to store conversation memories across sessions. Monitor stores both short-term (15 minutes) and long-term (60 minutes) conversation memories in Redis, allowing for robust session context. This ensures that LLM context and ongoing workflows can be reliably restored or continued after restarts. 

- **macOS (using Homebrew):**
  ```
  brew install redis
  redis-server
  ```
- **Linux (using apt):**
  ```
  sudo apt install redis
  redis-server
  ```
- **Windows:**
  Use WSL, Docker, or official binaries: [https://redis.io/docs/install/install-redis/](https://redis.io/docs/install/install-redis/)

## Installation

1. **Clone the repository:**
   ```
   git clone https://github.com/YOUR_ORG/monitor3.git
   cd monitor3
   ```
2. **Install Python dependencies:**
   ```
   pip install .
   ```
   Or for development:
   ```
   pip install -e .
   ```
3. **(Optional) Install and start Redis for advanced features:**
   - _On Linux/macOS (via Homebrew, apt, etc.)_:
     ```
     brew install redis
     redis-server
     ```
     OR
     ```
     sudo apt install redis
     redis-server
     ```
   - _On Windows:_  
     Use WSL, Docker, or supported binaries:  
     [https://redis.io/docs/install/install-redis/](https://redis.io/docs/install/install-redis/)

## Quickstart

### CLI Usage

Start an interactive Monitor shell from project root or any directory:
```
monitor
```
or
```
python -m monitor
```

For module development:
```
PYTHONPATH=src python -m monitor
```

### Server Mode

Run Monitor as a local HTTP API server:
```
monitor server
```
or
```
python -m monitor.server
```

### Basic Examples

- **Send a shell command for LLM-assisted explanation:**
  ```
  monitor "explain: ls -l"
  ```
- **Run a saved macro:**
  ```
  monitor macro deploy
  ```

- **Use API endpoint from another script:**
  See [src/monitor/README.md](src/monitor/README.md) for examples.

## Configuration and Usage Basics

Monitor loads configuration from `app.yaml` (for persistent settings) and optionally from `.env` (for secrets and environment tokens).

**Example:**
```yaml
model:
  provider: openai
  api_key: ${OPENAI_API_KEY}
registry:
  path: ~/.monitor/registry
```


Monitor can be used with your favorite LLM (OpenAI, Anthropic, xAI(Grok)).

- Place your `.env` file, which should contain your LLM access tokens, into your `~/.config/monitor` directory
```txt
# ~/.config/monitor/.env
OPENAI_API_KEY=<key>
ANTHROPIC_API_KEY=<key>
XAI_API_KEY=<key>
```
- Flags and environment variables can override YAML settings at launch.

**Usage Modes:**

- **Interactive shell**: Type commands, ask for code change suggestions, or interact directly with git context.
- **LLM direct queries**: "How do I optimize this function?" or "Review last commit" and receive in-place code modifications.
- **Macros**: Compose batch automations via reusable macro scripts.

See [ARCHITECTURE.md](ARCHITECTURE.md) or [src/monitor/README.md](src/monitor/README.md) for full configuration options.

## Extending Monitor

- **Custom Macros:** Write your own macros using YAML or Python and place them under the macros/ directory or user registry.
- **Plugin System:** Develop and register tool plugins for custom API/data access or new shell commands.
- **Registry:** Share and install trusted macros or plugins through the registry system. Registry uses Redis and supports full auditability.
- See devdocs in [src/monitor/README.md](src/monitor/README.md).



## Logging and Auditing

All Monitor operations are logged to the local registry (Redis-backed) and file-based logs. You can inspect, export, and replay previous session logs for compliance or debugging. Logs include:

- CLI/API invocations
- LLM prompts, completions, code actions
- Shell and code executions, results, and errors
- Macro executions and workflow traces

Logs are by default written to `~/.monitor/logs/`. Specify alternate log directories or output via `app.yaml`. Audit logs are essential for regulated, multi-user, or production settings.

## Troubleshooting

- **Redis connection issues:**  
  Ensure `redis-server` is running and accessible.
- **Invalid app.yaml or missing .env:**  
  Validate your config and environment variable values.
- **Unsupported OS / Python version:**  
  Use Python 3.9 or later on Windows 10+, macOS, or Linux.
- **LLM API errors:**  
  Confirm API keys and correct model provider setup.
- **Permissions or sandboxing errors:**  
  Check directory/file permissions and security configuration in `app.yaml`.

For more, see [src/monitor/README.md](src/monitor/README.md).

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
See test documentation in [src/monitor/README.md](src/monitor/README.md).

## License

Monitor is open source, distributed under the MIT License. See `LICENSE` for full terms.

## Contact

For issues or feature requests, please file an issue on GitHub:  
[https://github.com/YOUR_ORG/monitor3](https://github.com/YOUR_ORG/monitor3)

For architectural details and advanced extension, consult [ARCHITECTURE.md](ARCHITECTURE.md) and [src/monitor/README.md](src/monitor/README.md).
