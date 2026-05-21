# lib/ — Platform Integration and Extensibility Hub

This document describes the monitor.lib package: the integration, utility, and extensibility layer for the Monitor platform. It is intended to be practical and actionable for contributors who want to add, update, or integrate helpers, connectors, and stateful services.

Key points up-front
- monitor.lib contains focused modules that encapsulate single responsibilities (connectors, helpers, editors, memory, rate limiting, token accounting, etc.).
- monitor.lib.token_management is the canonical token counting and update API for the platform. Other modules (notably rate_limiter.py) should use that API rather than duplicating token accounting logic.
- rate_limiter.py provides request and token rate limiting with built-in token estimation.
- Several modules in lib are integration points with core systems (history, conversation, tooling, LLM adapters) and with external adapters (redis_utils, semantic_store, tool_loading).
- If you add a new helper module, register it with core or tool-loading when it provides tool-like behavior or needs to be exposed to macros/workflows.

High-level architecture
- Integration-first: connectors and adapters live here and are designed for rapid extension.
- Helpers and state infra: most modules are stateless utilities; a few (macros, memory, editors, logging) provide explicit stateful services.
- Plug-and-play: add new modules as single files under lib/, follow minimal dependency rules, and register where appropriate.
- Explicit state: prefer pure functions; surface stateful behavior through clear, well-documented APIs.

Files in src/monitor/lib (one-line responsibilities)
- built_in_commands.py — Common built-in commands and shared platform helper command implementations.
- built_ins_utils.py — Utilities for registering and managing built-in helper functions and commands.
- colors.py — Terminal and UI color helpers and color scheme utilities.
- command_utils.py — Command definition, parsing, and execution utilities for CLI and macro invocation.
- commit_analysis.py — High-level commit analysis and summary helpers (semantic interpretation of diffs/commits).
- commit_analyzer.py — Legacy/bridge Git commit analysis helper (compatibility shim for older workflows).
- consult.py — Consultative AI/system orchestration helpers and templating utilities.
- db_storage.py — DuckDB/Postgres connection helpers and query abstractions used by storage-backed features.
- deployment.py — Helpers and utilities for deploying code, models, or artifacts.
- display_output.py — Formatting, streaming, and display management utilities for UI and logs.
- ecs.py — AWS ECS integration helpers and deployment orchestration utilities.
- external_services.py — Utilities for publishing artifacts and posting to social platforms (Twitter, Twitch, LinkedIn, etc.).
- file_io.py — Filesystem reading/writing, path utilities, and safe file helpers.
- git.py — Git command wrappers and version control helpers.
- git_utils.py — Additional Git utilities and version control helpers.
- history.py — Persistent or session-based history management used by core conversation/history features.
- input_modes.py — Helpers for managing and switching interactive input modes.
- keyboard.py — Keyboard event handling and shortcut utilities for interactive UIs.
- lexer.py — Syntax highlighting, lexing, and prompt-toolkit integration for autocompletion and display.
- llm_utils.py — Utilities for LLM adapters, prompts, and response handling.
- logging.py — Robust logging, auditing, and trace utilities for platform events and actions.
- macro_utils.py — Macro expansion helpers, validation, and utility functions for macro workflows.
- macros.py — Persistent macro definitions, orchestration, storage, and macro lifecycle management.
- message_utils.py — Formatting and managing system and LLM messages; conversation content helpers.
- modeling.py — Data science / ML model helpers and basic training / inference utilities.
- os.py — OS compatibility helpers and platform bridging (legacy/compatibility shim).
- preferences.py — User and system preference loading, saving, and management helpers.
- preprocessing.py — Input and data preprocessing pipelines and utilities used by prompts and tools.
- progress.py — Progress tracking and display utilities for long-running tasks.
- protocol_engine.py — Protocol and streaming execution engine abstractions used by streaming components.
- rag.py — Retrieval-augmented generation helpers that combine search results and context for LLMs.
- rate_limiter.py — Rate limiting utilities and token/request throttling with built-in token estimation.
- redis_utils.py — Redis-based persistent memory/context helpers and fast storage adapters.
- ripgrep_search.py — High-performance project/file search wrapper around ripgrep.
- semantic_store.py — Embedding and semantic similarity helpers, and a context store interface for retrieval.
- server.py — HTTP server helpers and Flask integration utilities.
- signal_handler.py — OS signal handling and graceful shutdown utilities.
- sound.py — Audio playback and sound effect helpers.
- summarizers.py — Text and chat summarization helpers using LLMs or heuristic approaches.
- system_prompt.py — System prompt management and prompt editing/orchestration helpers.
- terminal_commands.py — Shell subprocess orchestration and command launching utilities.
- text_file_editor.py — Stateful text/buffer editor logic, undo/redo, and editor session management.
- text_to_speech.py — Speech output utilities for LLM or system messages.
- token_management.py — Canonical token counting, usage tracking, and update API for LLM requests; used across platform features.
- todo.py — Task and todo list management utilities.
- todo_redis.py — Redis-backed persistence for todo lists.
- tool_definitions.py — Schemas and definitions for tool/function/plugin structures exposed to workflows and LLMs.
- tool_loading.py — Dynamic tool loading, discovery, and function definition registration utilities.
- voice_to_text.py — Speech-to-text helpers and audio input utilities.
- weather.py — External weather data adapter and simple API helper utilities.
- web_search.py — External web search connector utilities and search result normalization.

Key integrations and responsibilities
- Core integration points:
  - history.py is the canonical integration point for persistent conversation/history storage and is used by core conversation and UI layers.
  - message_utils.py, macros.py, and macro_utils.py are used by orchestration layers (core) to drive macro execution and message flows.
  - tool_definitions.py and tool_loading.py are the bridge between lib/ helpers and core tooling/macro systems — register tools here so core/tooling can discover and invoke them.
  - modeling.py, rag.py, and preprocessors are frequently used by core LLM adapter workflows to prepare context and inputs.
- External adapters and stores:
  - redis_utils.py provides a Redis-backed memory/context store for session persistence and fast access.
  - semantic_store.py provides embedding and vector search integration for retrieval.
  - tool_loading.py is the canonical place for registering dynamically-discoverable tools that may interact with external adapters.
- Token & rate control:
  - token_management.py is the canonical API for counting and updating token usage across LLM requests. All modules that consume or charge tokens MUST call into this API to ensure consistent accounting and telemetry.
  - rate_limiter.py implements transport/request throttling with built-in token estimation to enforce limits and telemetry.
  - Note: the low-level estimator estimate_token_count is implemented in monitor.lib.rate_limiter, but callers must use the monitor.lib.token_management API (count_message_tokens, update_token_usage) instead of calling the estimator directly.

Security and server note
- server.create_flask_server (or the server module's create_flask_server helper in the project) can be used to quickly start a local HTTP server for integrations and testing.
- Security warning: Do NOT bind the development Flask server to 0.0.0.0 (non-localhost) in production or on untrusted networks. The default development server is not hardened; if you need remote access, run behind a production-grade WSGI server (Gunicorn/uvicorn) and secure the endpoint (TLS, authentication, firewall).

Contributor guidance — adding a new helper module
1. Create the module
   - Add a single Python file under src/monitor/lib with a focused responsibility.
   - Keep external dependencies minimal; prefer pure functions where possible.
   - Include docstrings and small usage examples in the module header.

2. Design API and state
   - If the module is stateless, expose small pure functions that accept explicit inputs and return deterministic outputs.
   - If the module requires state (memory caches, editor sessions, macros), expose a small class or well-defined manager object and document lifecycle expectations.

3. Integration & registration
   - If your helper should be exposed as a tool/function to macros or the orchestration layer, register it via tool_definitions.py and tool_loading.py so core tooling can discover and invoke it.
   - Note that functions like add_tool typically manage descriptions and tool state, but the callable implementation must also be registered in tool_definitions.AVAILABLE_TOOLS (or wired during configure_tools) so the runtime can invoke it.
   - If your helper interacts with persistent memory, prefer using redis_utils.py or semantic_store.py adapters rather than re-implementing storage logic.
   - If your helper affects token usage, call monitor.lib.token_management APIs to report consumption and updates.

4. Tests and portability
   - Add unit tests under tests/ that exercise pure logic and edge cases.
   - Provide integration tests or a small example script showing how the module is wired into core workflows if applicable.
   - Ensure cross-platform behavior for file/OS utilities; prefer higher-level stdlib helpers.

5. Documentation
   - Add a short README or docstring demonstrating intended usage and integration points.
   - If the module is a bridge to legacy behavior, clearly label it as a compatibility shim and document expected migration paths.

6. Security and operational considerations
   - Validate and sanitize external inputs (URLs, files, command strings).
   - Limit network calls and provide configurable timeouts for external adapters.
   - For any server-facing feature, document expected threat model and required operational hardening.

Examples of registration (patterns)
- Tool registration (conceptual)
  - Define a tool schema in tool_definitions.py.
  - Ensure tool_loading.py can discover and instantiate the tool using a lightweight factory.
  - Surface the tool name and input/output schema to orchestration layers so macros and workflows can call it.

- Token reporting (conceptual)
  - Before an LLM call: tokens = token_management.count_message_tokens(messages)
  - After an LLM response: token_management.update_token_usage(response_or_count)

Style and maintainability notes
- Keep functions small and focused; prefer composition over large monolithic helpers.
- Favor explicit dependencies injected as parameters (clients, adapters) rather than global singletons where testability matters.
- Preserve backward-compatible behavior in bridge modules (os.py, commit_analyzer.py). Document deprecation timelines when making breaking changes.

Contact and escalation
- If your change affects token accounting, rate limiting, or persistent memory, add a note in the PR description describing the integration points touched and notify the platform core maintainers for review.
- For questions about registering tools or adjusting tooling discovery, refer to the tool_loading.py docs and contact the tooling owner on the engineering channel.

This README is intended to help contributors quickly understand responsibilities, integration points, and safe extension patterns for src/monitor/lib. Follow the guidance above to keep the library modular, testable, and operable across the platform.
