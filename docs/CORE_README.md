# Monitor Core README

This document describes the responsibilities, runtime flows, and extension points for the code under src/monitor/core. It is intended to be a practical, actionable reference for contributors who are adding commands, tools, macros, or changing core orchestration.

Short overview
--------------
The core/ package implements the central orchestration for Monitor: conversation state and loop, command and tool registries, macro dispatch, LLM adapters, and the runtime routing that connects CLI and HTTP modes to shared business logic. Core delegates infrastructure concerns (token accounting, persistence, tool loading, external integrations) to monitor.lib to avoid tight coupling.

File map (each file present in src/monitor/core)
------------------------------------------------
- built_ins.py
  - Registers built-in commands and integrates any platform-level tool startup logic.

- command_processing.py
  - Parses incoming user input or API payloads and routes them to the correct handler (command, macro, tool, or conversation flow).

- commands.py
  - Implements concrete command handlers, parameter validation, and small utility commands that run within Monitor.

- commit.py
  - Tracks application commit/version metadata and exposes it to sessions and logs for auditability.

- conversation.py
  - Implements the conversation/chat loop, message history plumbing, prompt assembly, and the interface that mixes LLM responses with tool invocations and command executions.

- internalize_commands.py
  - Wraps or adapts commands to reduce coupling between shell-like operations and conversation state; used when commands need special mediation.

- llm.py
  - LLM adapter layer and preference management for LLM backends; constructs model requests, handles streaming vs. non-streaming, and normalizes responses into core’s message model.

- llm_responses_adapter.py
  - Normalizes and adapts raw LLM outputs into core's message/event model.

- modes.py
  - Handles design and development mode commands and logic for toggling operational modes in sessions.

- query_service.py
  - A small request/response interface that centralizes inter-module queries to break circular imports between registries, tools, and services.

- tooling.py
  - High-level invocation flow for tool and macro execution: argument marshaling, sandboxing/validation, and result normalization.

- tools.py
  - Tool registry and abstraction layer for tools available to the CLI and LLMs. Exposes discovery metadata and runtime invocation helpers.

Key runtime flows
-----------------

Conversation / chat loop
- Entry points:
  - CLI: app.py initializes a session and calls conversation.chat() which yields prompts, collects user lines, and drives responses.
  - HTTP API: app.py forwards REST payloads to server endpoints (src/monitor/lib/server.py) which call conversation.query() for stateless or session-backed conversation handling.
- Flow:
  1. Assemble context window from history (monitor.lib.history) and session metadata.
  2. Apply mode-specific transformations (monitor.lib.input_modes) to shape the prompt and expected output format, using helpers determine_input_mode/process_input_mode.
  3. Call llm adapter to get model output, or route to command/tool if model output indicates an action.
  4. If a tool/macro/command is invoked, pause LLM flow, run tooling/tooling.py or commands.py, persist result to history, and resume LLM if needed.
  5. Emit structured audit logs and return the combined output to caller.

Command evaluation and execution
- Parsing and routing:
  - command_processing.py normalizes input and determines whether a tokenized input is a built-in command, user command, or macro trigger.
- Execution:
  1. Validate arguments using command definitions in commands.py.
  2. Use internalize_commands.py if the command needs mediation with conversation state.
  3. Execute the handler synchronously or asynchronously; tooling.py may be used for commands that invoke external tools.
  4. Record call and outputs in history and structured logs for audit and replay.

Tool and function call flow
- Discovery:
  - tools.py exposes registered tools and metadata that LLMs or the CLI can discover.
- Invocation:
  1. tooling.py marshals arguments (type coercion, validation), enforces permission checks, and calls the underlying tool function.
  2. monitor.lib.tool_loading may be used to load external tool implementations at startup.
  3. Results are normalized, optionally stored in history, and surfaced to the LLM or user.
  4. Tool calls are audited and token/accounting annotations are attached for billing and tracing.

LLM adapter paths
- llm.py is the single adapter surface inside core for model interaction. It:
  - Builds prompt payloads (including system/user/messages and metadata).
  - Chooses streaming vs. non-streaming API paths.
  - Normalizes responses into core's message/event model.
  - Emits events/hooks for tooling to intercept suggested actions from the LLM.
- Integration:
  - Usage of monitor.lib.token_management is required for token accounting before/after LLM calls.
  - LLM preferences and routing may be configured at session or system level and read by llm.py.

Integration points with monitor.lib
-----------------------------------
Core relies on monitor.lib for infra responsibilities to keep core focused on orchestration. Key integration points include:
- monitor.lib.token_management
  - Centralized token accounting, rate limits, and token budgeting. All LLM calls and token-sensitive flows in core must use this module.
- monitor.lib.tool_loading
  - Dynamic loading of external tool implementations and adapters. tools.py and built_ins.py use this to register available tools.
- monitor.lib.macros
  - Persistent macro storage, macro expansion, and discovery. conversation and tooling consult this module for macro execution.
- monitor.lib.history
  - Persistent and in-memory conversation history. conversation.py and command handlers read/write through this API for consistent storage and replay.
- monitor.lib.external_services (or similarly named adapters)
  - SDKs and adapters for external APIs, credential management, and long-lived service clients used by tools and commands.

Purpose of query_service
------------------------
query_service.py exists to centralize inter-module queries and avoid circular imports between registries, tools, and services. Use it when:
- A module needs to obtain a service, registry entry, or perform a lookup without importing concrete modules that would create cycles.
- You want a lightweight indirection that can be mocked in tests or replaced with alternate implementations in downstream builds.

Guidance for contributors
-------------------------

Adding a tool
1. Implement the tool function in a new module under core/ or in a lib/ adapter if it requires external services.
2. Export a registration function or metadata object and register it during startup from built_ins.py or via monitor.lib.tool_loading.
3. Decorate or annotate tool metadata if it should be discoverable to LLMs (name, description, argument schema).
4. Add tests for argument validation, edge cases, and failure/permission behavior.

Adding a command
1. Add the handler function or class in commands.py (or split into a small module for large commands).
2. Define the parameter schema, help text, and registration entry used by command_processing.py.
3. If the command interacts with conversation state, consider using internalize_commands.py to mediate state coupling.
4. Wire the command into built_ins.py or the relevant registry initialization path.

Adding a macro
1. Define the macro in the macro registry (monitor.lib.macros) with the canonical expansion logic and optional parameter schema.
2. Register the macro on startup so it is discoverable by conversation.py and tooling.py.
3. Include tests for expansion, argument interpolation, and nested macro behavior.

Design and development modes
----------------------------
- modes.py handles design and development mode commands and logic for toggling operational modes in sessions. Note that input modes (single-line prompt, multiline, pipeline, voice/stream) are handled by monitor.lib.input_modes.
- Use the modes layer to make changes that affect how prompts are assembled or how the UI expects data (do not embed mode-specific logic directly in conversation flows).

Rate limiting and token accounting
----------------------------------
- Core enforces request policies and local helpers (rate_limiting.py), but authoritative token accounting and billing enforcement live in monitor.lib.token_management.
- All LLM calls and any code paths that consume tokens MUST call into monitor.lib.token_management to:
  - Use monitor.lib.token_management.count_message_tokens to estimate and reserve tokens before API calls.
  - Use monitor.lib.token_management.update_token_usage to reconcile usage after streaming or completion.
  - Apply per-session or per-tenant caps consistently.

Testing and observability
-------------------------
- Unit-test command, tool, and macro handlers in isolation, mocking monitor.lib dependencies.
- Integration tests should cover end-to-end conversation flows (conversation -> llm -> tooling -> history).
- All core flows should emit structured logs (JSON) that include session id, user id (if available), call ids, and token accounting snapshots for audit.

See also
--------
- docs/ADD_LLM_TOOL.md
- docs/ADD_BUILT_IN.md
- docs/MACROS_README.md
