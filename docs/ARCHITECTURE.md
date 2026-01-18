# Monitor System Architecture (2024 Update - Modular, Auditable, Extensible)

Monitor is a secure, modular, LLM-powered developer assistant for automation, productivity, and AI/data science workflows, emphasizing robust auditability, modular integration, and resilience. Its design ensures maintainability and clarity for new contributors and supports advanced operation modes, extensibility, and high-trace compliance.

===============================================================================
Key File / Module Table
===============================================================================
| File / Module            | Role / Responsibility                                            |
|--------------------------|-----------------------------------------------------------------|
| app.py                   | Main entry point: orchestrates CLI/event loop and HTTP server;   |
|                          | initializes logging, core modules, registries, session handling, |
|                          | signal cleanup, extensibility. app.py initializes the Flask app |
|                          | via the factory in src/monitor/lib/server.py for server mode.    |
| core/conversation.py     | Conversational event/chat loop abstractions for CLI and API.     |
| core/command_processing.py| Aggregates command dispatch, routing, safety checks (built-ins, |
|                          | system shell, macros).                                          |
| core/built_ins.py        | Source of built-in commands and system-level operations.         |
| lib/macros.py            | Macro registration, expansion, parameterization, automation.     |
| core/query_service.py    | Broker for LLM, tool, and macro queries—drives routing between   |
|                          | CLI, LLM, macros, and core logic.                               |
| config.py / config.yaml     | Configuration profiles: model options, limits, credentials, etc. |
| logs/                    | Centralized, session-aware, rolling and audit logs; logs are     |
|                          | written to configured paths and created at runtime.              |
===============================================================================

===============================================================================
High-Level Architecture Diagram (ASCII)
===============================================================================
                +-------------------------+
                |        app.py           |
                |-------------------------|
                | - CLI loop (interactive)|
                | - HTTP server (Flask)   |
                | - Registers, initializes|
                |   and manages           |
                |   modules and logs      |
                +--------+----------------+
                         |
         -------------------------------------------
         |                    |                    |
+----------------+  +-------------------+  +---------------------+
|  core/         |  |    core/          |  |     core/           |
|  conversation  |  | command_processing|  |  query_service      |
+----------------+  +-------------------+  +---------------------+
         |   (handles event/chat loop)   |            ^
         +---------------+--------------+            |
                         |                           |
                +-------------------+                |
                |      core/        |                |
                |    built_ins      |    +---------------------+
                +-------------------+    |   lib/macros        |
                    (CLI macros,         +---------------------+
                    tools registry,      | macro registration, |
                    base commands)       | expansion, hooks,   |
                                          | tool registry  |
                                           +-------------------+
===============================================================================

## 1. Top-Level System Summary

Monitor consists of orchestrated Python modules with tight audit, session, and security controls. The **entry point is always `app.py`**, which determines the system mode (interactive CLI via prompt_toolkit or HTTP server via Flask), initializes modular registries, config, logging, context, macro hooks, and sets up graceful signal handling and session cleanup.

**Key Features:**
- Modular core (`core/`) and integration layer (`lib/`), registered and bootstrapped in `app.py`
- All command registration/dispatch flows through centralized registries and handler maps: `core.built_ins`, `lib.macros`, `core.command_processing`
- Dual-mode operation: **Interactive CLI Loop** or **HTTP API Server** (each with observability, audit, and graceful shutdown)
- **Conversation abstraction:** `core/conversation.py` manages dynamic chat/event loop, session context, and interactivity for both CLI and server modes
- **API Broker:** `core/query_service.py` provides LLM and tool brokering (mediates requests in both CLI and server)
- **Extensibility:** via server APIs, CLI/command registry, macro/hooks integration, and tool registry—all secured and auditable

## 2. Dual-Mode Operation

**A. Interactive CLI Loop**
- Invoked by default via `app.py` (unless --server flag or env specified)
- Uses prompt_toolkit for multiline, syntax-highlighted input, context cues, and live macro expansion
- Handles registration of built-ins, macros, and command processors
- Event/chat loop controlled by `core/conversation.py`—with command processing mediated via `core.command_processing`
- Logs all actions (session, audit, error) in timestamped/rotating logs under `logs/` that are written to configured paths and created at runtime
- Session and signal handlers: session ID, Ctrl+C/BREAK event cleanup, graceful exit with final audit logging
- CLI entrypoint: conversation.chat() in core/conversation.py is the main interactive entrypoint for the CLI mode

**B. HTTP Server API**
- Enabled by `--server` flag in `app.py`; app.py initializes the Flask app via the factory in src/monitor/lib/server.py for stateless API endpoints
- Server endpoints and their routing are defined in src/monitor/lib/server.py; app.py calls into that factory (e.g., server.create_flask_server()) and manages process/thread-level integration
- Exposes endpoints for:
    - Submitting commands/queries for processing
    - Fetching conversation/context state
    - Extending backend via custom API requests (extensions/tools)
    - Health, metrics, and logging endpoints
- All queries/requests routed via `core/query_service.py` broker, ensuring tool/macro/core command mediation
- Server shutdowns handled with registered Flask and app signal handlers; logs persisted across sessions

## 3. Central File Roles (Expanded)

- **`app.py`:**
    - Always the entry point—sets up logger, config, context/memory, CLI/server mode selection, macro/command registration, tool registry installation
    - Encapsulates the main CLI entrypoint (calls conversation.chat() in core/conversation.py), sets up Flask API in server mode via the server factory
    - Handles all signal trapping (SIGINT/SIGTERM), session teardown and persistent artifact/summary emission

- **`core/conversation.py`:**
    - Abstracts chat loop and event model for both CLI and API, managing session context, prompt rendering, and context window
    - Securely handles user input processing, message threading, and interaction state for both live and programmatic entry

- **`core/command_processing.py`:**
    - Responsible for command routing: dispatches inputs to:
        - Built-ins—registered in `core.built_ins`
        - Macro hooks—registered in `lib.macros`
        - Shell/system commands—safely checked and executed
    - Contains safety validation, privilege checks, and error handling boundaries

- **`core/built_ins.py`:**
    - Defines core built-in commands and tool behaviors (ls, cat, git, Python eval, etc.)
    - All registered via centralized registry in app/bootstrap

- **`lib/macros.py`:**
    - Macro engine: macro registration, parameter parsing, scriptable/LLM-assisted expansion
    - Macro registry can be extended live via CLI or config; supports hooks into command processing

- **`core/query_service.py`:**
    - Central broker for tool/integration queries and LLM activity
    - Mediates between CLI/server, macros, and integrations—ensures all actions are auditable

- **`config.py` / `config.yaml`:**
    - Configuration for tools, LLMs, logging, limits, credentials, persistent memory, summarization
    - Some runtime components (for example, macro definitions and certain registries that are primarily runtime data structures) support explicit runtime reload mechanisms. These are implemented as explicit "reload" hooks or re-initialization entrypoints (for example, a configure_tools / registry re-run path) that refresh registry state, macro definitions, and related runtime data without restarting the whole process. This capability is limited to refreshing runtime-configurable data and registry entries; it does not provide process-level code hot-reload (you cannot dynamically replace arbitrary Python modules or change the process-executed code across the entire running process). See lib/macros.py for macro registration and available reload hooks, and app.py for registry initialization and configure_tools re-run entrypoints and patterns for safe runtime refresh.

- **Logging and Auditing (`logs/`):**
    - Central session-log, full audit trace (commands, LLM, errors) in session-aware log files
    - Rotating logs, real-time streaming, replayable audit trail
    - Logger is initialized in `app.py` and used system-wide; logs are written to configured paths and created at runtime

## 4. Chat Loop and Server API—Details

**Chat Loop (`core/conversation.py`):**
- Orchestrates prompt_toolkit CLI interactive sessions, context-tracking, and event-based input handling
- Receives user/LLM input, feeding into command processor and macro registry
- Supports output capture, error injection, context trimming, summarization, and token window management
- Underpins both standalone CLI and server-interactive API chat endpoints
- Entry point for interactive sessions: conversation.chat()

**Server API (Flask integration):**
- Server endpoints live in src/monitor/lib/server.py as a Flask app factory; app.py initializes the Flask app via that factory
- Each API query/event is dispatched via the same brokers and registries used by CLI mode
- State, logs, audit, and context history are uniform across CLI and server
- API extensibility: register new endpoints as modules under `lib/`, integrating via the command/macro registry

**Query Broker (`core/query_service.py`):**
- Unified entry point for LLM/tool invocation, macro expansion, summarization, intent inference
- Handles rate-limiting, error mediation, context possession, and logging for every tool/LLM action

===============================================================================
Extensibility Points
===============================================================================
- **Core Registry:** Register new built-ins (core.built_ins), macros (lib.macros), or tools (via tool registry)
- **Macro Engine:** Programmatically define/extend macros (lib.macros), register automation, post-processing hooks
- **Server API:** Extend via additional Flask endpoints (integrate via app.py/lib/), or expose new HTTP-facing services
- **CLI Tools:** Register/hook new commands at startup/session-init via app.py or hot-reload logic
- **Hooks and Extensions:** All tool/macro/command registration flows are centralized for audit and context
===============================================================================

## 5. Session Audit, Logging, and Cleanup

- **Logging:** All system, CLI, tool, LLM, and error events are timestamped. Log sessions are rolling, replayable, and redactable; debug/audit mode controls verbosity and retention policy. Logs are written to configured paths and created at runtime.
- **Signal Handling / Session Teardown:**
    - Robust SIGINT/SIGTERM catchers for CLI and server
    - Ensures context summaries, log finalization, and any temporary state/artifacts are cleaned on shutdown
    - Session audit and error logs closed and made available at run completion
- **Memory and Context:**
    - Proactive context trimming, summarization via LLMs as needed (see config)
    - Optional persistent context/memory layers (Redis or file-backed store) for long-term recall

===============================================================================
For architecture diagrams, maintainers’ docs, and up-to-date developer best practices: see README.md or contact the current maintainers.
===============================================================================

Where to look in the code:
- core/conversation.py -> conversation.chat
- src/monitor/lib/server.py -> server.create_flask_server
- core/command_processing.py -> core.command_processing.process_command
- core/query_service.py -> core.query_service

===============================================================================
