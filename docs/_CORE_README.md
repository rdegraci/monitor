# Monitor Core Module

The `core/` directory is the foundation of all modular logic and orchestration in the Monitor system. It powers conversation state, command/macro/tool registries, extensibility protocols, and lifecycle flows for both CLI and HTTP operations. All core functionality is orchestrated exclusively through the central entry point: `app.py`.

---

## High-Level Flow

        ┌──────────────┐
        │   app.py    │  ← single Monitor entrypoint (CLI & API)
        └─────┬────────┘
              │
        ┌─────▼──────────────────┐
        │      core/             │
        │  (registries, modules, │
        │   macros, LLM, tools,  │
        │   conversation, state) │
        └─────┬──────────────────┘
              │
        ┌─────▼───────┐
        │   lib/      │  ← infrastructure, adapters, persistence, UI
        └─────────────┘

---

## Architectural Overview

- **app.py**: Entrypoint that initializes and mediates all Monitor operations across CLI and HTTP API modes.
- **core/**: Encapsulates modular extensibility—the registry of commands, macros, tools and services, dispatcher framework, persistent conversation/memory state, secure structured logging, extension interfaces, and conversation orchestration.
- **lib/**: Utility layer below core for persistence (e.g., Redis), adapters, infrastructure, user interface helpers, and external integration points.

---

## Dual Operational Modes

`core/` enables Monitor to run as:
- **Interactive CLI:** The core chat and tool dispatch loop with rich prompt UX.
- **HTTP API:** Stateless or sessioned conversation endpoints, proxying the same core logic to enable automation, embedding, and remote clients.

---

## Major Patterns and Responsibilities

- **Registry-Driven Extensibility:** 
  - All commands, macros, and tools are registered via core module registries, supporting modular and dynamic extension both at startup and runtime.
  - New features (incl. third-party) can be onboarded by adding files to `core/` and registering them through registry APIs.
- **Conversation State & Memory:**
  - Conversation loop, session state, memory/context-windows, and audit trails are orchestrated and persisted via core modules.
- **Secure Structured Logging & Audit:**
  - Fully structured, JSON/flat log output for key flows ensures session context and compliance-ready auditing of user, tool, and LLM activity.
- **Dispatch & Routing:**
  - Unified router for commands, macros, and tool invocations channels input across user, system, and LLM backends.
- **Macro, Tool, Command, and Service Onboarding:**
  - Clear interfaces for adding/extending macros, tools, shell/built-in commands, and internal services.
- **Extension Hooks:**
  - Each registry and event flow exposes hooks for future extension or override in custom or downstream Monitor builds.

---

## Core Module File Map

| File                    | Responsibility / Role                                                      |
|-------------------------|-----------------------------------------------------------------------------|
| `built_ins.py`          | Registers core commands, built-ins, and startup integration of external tools.    |
| `command_processing.py` | Unified dispatcher for parsing and routing all commands/macros/tools.           |
| `commands.py`           | Implements Monitor/user/system commands and argument validation logic.           |
| `commit.py`             | Tracks commit/version and session operation for state and logs.                  |
| `conversation.py`       | Manages chat loop, prompt flows, macro/command dispatch, and history.            |
| `internalize_commands.py` | Internalizes and mediates some commands to decouple shell and state flows.      |
| `llm.py`                | LLM API interface, preferences, rate limiting, and prompt context handling.      |
| `modes.py`              | Parses and validates input modes: prompt line, multiline, pipeline, voice.        |
| `query_service.py`      | Mediates query/service requests between decoupled modules or registries.          |
| `rate_limiting.py`      | Enforces API/system/LLM rate limits and token budgeting.                         |
| `tooling.py`            | Tool and macro invocation interfaces for LLM and system actions.                  |
| `tools.py`              | Core registry and abstraction for command-line and LLM-available tools.           |

---

## Extending Monitor Core: Onboarding Guide

**To Add a Tool:**  
1. Implement the tool logic in `core/tools.py` or as a new file imported therein.
2. Register the tool with the core `tools` registry at startup by calling its registration interface.
3. If LLM-available, decorate as LLM-discoverable via core-provided metadata.

**To Add a Command:**  
1. Define the handler function/class in `core/commands.py` or a related module.
2. Register the command and its parameters/types in the relevant command registry.
3. Use the core dispatcher to wire CLI/API invocation.

**To Add a Macro:**  
1. Extend/create macro definitions (with argument schema) in the macro registry.
2. Register the macro with the macro registry at startup.
3. Optionally expose macro triggers/dispatchers in conversation flows.

**To Add an Internal Service:**  
1. Define the logic in a suitably named new module (e.g., `core/query_service.py`).
2. Expose public methods for inter-module queries—avoid circular dependencies by using this layer.
3. Register/init via the service registry where necessary.

---

## Key Design Principles

- **Registry Pattern:** All platform logic is registered, discoverable, auditable, and dynamically extensible.
- **Single Control Surface:** `app.py` is the canonical orchestrator—no code outside of core and lib should own global control logic.
- **Auditability & Safety:** Persistent, structured logs on all user interaction, tool/macro activity, LLM output, and command routing.
- **Contextual Memory:** Short/long-term context windows adaptively managed and pruned, supporting persistent memory and compliance requirements.
- **CLI & HTTP API Parity:** Core flows are shared between interactive and programmatic (API) clients.
- **Isolation & Testability:** Service/query layers in `core/` are decoupled for more reliable testing and downstream extension.

---

For deeper architectural or onboarding help, see code-level docstrings or the dedicated Monitor developer guide.
