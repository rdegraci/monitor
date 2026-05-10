# MONITOR_OOP_IMPLEMENTATION_SEQUENCE

## Phase 1: Foundation
1. Create `src/monitor_oop/`.
2. Add `__init__.py`.
3. Add `models.py` with enums and dataclasses.
4. Add `context.py` with `RuntimeContext`.
5. Add `config_service.py`.
6. Add `prompt_store.py`.
7. Add `prompt_service.py`.

Phase 1 is complete: the foundation package, models, runtime context, config service, and prompt loading/storage are in place, and the early bootstrap layer now seeds missing user config files from the packaged examples while preserving any existing `appdirs.user_config_dir("monitor")` files.

## Configuration Bootstrap
- `src/monitor_oop/config.yaml.example` is present and is used to seed missing `appdirs.user_config_dir("monitor")/config.yaml` files.
- Existing `appdirs.user_config_dir("monitor")/config.yaml` files are preserved.
- Only missing `appdirs.user_config_dir("monitor")/config.yaml` files are seeded from `src/monitor_oop/config.yaml.example`.
- On first run, copy it to `appdirs.user_config_dir("monitor")/config.yaml`.
- Load `config.yaml` from the user config directory, with fallback to `~/.config/monitor/`.
- Load `.env` with `find_dotenv(usecwd=True)` plus user config fallbacks.
- `src/monitor_oop/system_prompt.example` is present and is used to seed missing `appdirs.user_config_dir("monitor")/system_prompt` files.
- Existing `appdirs.user_config_dir("monitor")/system_prompt` files are preserved.
- Only missing `appdirs.user_config_dir("monitor")/system_prompt` files are seeded from `src/monitor_oop/system_prompt.example`.
- On first run, copy it to `appdirs.user_config_dir("monitor")/system_prompt`.
- Load the resolved system prompt from the user config directory, with fallback to `~/.config/monitor/`.
- Wire the resolved prompt into LLM request construction as the first system message.

## Phase 2: Core services
6. Add `history_service.py`.
7. Add `macro_service.py`.
8. Add `status_service.py`.
9. Add `command_processor.py`.

Phase 2 is complete: the core services and command processor are implemented, including tool-calling support for multi-call extraction, envelope recording, and batched follow-up payloads using `call_id`. The tool-calling refactor is complete and now uses direct Responses API parsing from `response.output`; `parse_tool_call` and `parse_tool_calls` were removed, and current coverage verifies `extract_tool_calls`, multi-call handling, batched follow-up payloads, and `ToolTurnState` lifecycle management. `LLMRequestBuilder` and `LLMResponseClient` have been extracted into `src/monitor_oop/core/application/`, and both are covered by dedicated tests. `ToolCallHandler` has been extracted into `src/monitor_oop/core/tools/tool_call_handler.py` and is covered by dedicated tests, with the tool-turn lifecycle now owned through the handler.

## Phase 3: Session and workflows
10. Add `conversation_session.py`.
11. Add `workflow.py` with orchestration functions.
12. Add `app.py` with `MonitorApp`.

Phase 3 is complete: the session/workflow layer is implemented, and the current CLI thin slice is runnable end to end in `src/monitor_oop/core/`. The classic CLI REPL remains the default interactive mode, while the prompt_toolkit TUI is available as a separate `--tui` path. Prompt loading happens early in the thin slice so the first system message is available to the request builder from the start, and the default REPL logs to both screen and file while `--tui` uses file-only logging. The log file path follows the user config directory convention under `log/monitor_<pid>.log`. TUI startup uses a quiet bootstrap path so the TUI can start with file-only logging while runtime output stays off the screen.

## Phase 4: Server
13. Add `server_app.py`.
14. Wire the HTTP API through `RuntimeContext` only.

Phase 4 remains future work: server wiring is still pending.

## Phase 5: Thin slice
15. Make one CLI path runnable end to end.
16. Keep the first version narrow: config load, session creation, prompt, one command, exit.

The thin-slice CLI milestone is achieved in `src/monitor_oop/core/`: the first-stage flow now runs from config load through one command and exit, with OpenAI API key handling using the current environment lookup plus the `~/.config/monitor/.env` fallback. Prompt loading is included in the early bootstrap path, and the resolved prompt is injected into LLM request construction as the first system message. The default interactive experience is the classic CLI REPL, which logs to both screen and file, and the separate `--tui` entry path uses file-only logging so the TUI can start without screen output; the log file path follows the user config directory convention under `log/monitor_<pid>.log`. The TUI path still uses quiet bootstrap startup so the UI can initialize cleanly.

## Phase 6: Tests
17. Add startup tests.
18. Add config service tests.
19. Add command processor tests.
20. Add conversation session tests.
21. Add server tests.
22. Add isolation tests that confirm no legacy globals are touched.

The new tests cover the first-stage flow, including startup, config service, command processor, conversation session, and isolation coverage. The test suite has been reorganized to mirror `src/monitor_oop/core/` and `src/monitor_oop/core/tools/` under `tests/monitor_oop/core/` and `tests/monitor_oop/core/tools/`.

## Implementation Notes
- Prefer small constructors with explicit dependencies.
- Use free functions only for orchestration.
- Keep shared helpers pure where possible.
- Avoid introducing circular imports between services.
- Keep the legacy app unchanged during this sequence.
- Load the resolved prompt early so request construction can consistently prepend it as the first system message.
- Keep the classic CLI REPL as the default interactive mode.
- Treat the prompt_toolkit TUI as a separate `--tui` path.
- Use quiet bootstrap for TUI startup.
- The default REPL logs to both screen and file, while `--tui` uses file-only logging.
- Write logs under the user config directory `log/` subdirectory as `monitor_<pid>.log`.

## Future Work
- Complete server work.
- Add real LLM integration in a later phase.
- Expand beyond the initial CLI thin slice once the server and model-backed paths are ready.
