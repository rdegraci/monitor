# MONITOR_OOP_IMPLEMENTATION_SEQUENCE

## Phase 1: Foundation
1. Create `src/monitor_oop/`.
2. Add `__init__.py`.
3. Add `models.py` with enums and dataclasses.
4. Add `context.py` with `RuntimeContext`.
5. Add `config_service.py`.

Phase 1 is complete: the foundation package, models, runtime context, and config service are in place.

## Configuration Bootstrap
- Next planned work is to add `config.yaml.example` in `src/monitor_oop/`.
- Existing `appdirs.user_config_dir("monitor")/config.yaml` files are preserved.
- Only missing `appdirs.user_config_dir("monitor")/config.yaml` files are seeded from `src/monitor_oop/config.yaml.example`.
- On first run, copy it to `appdirs.user_config_dir("monitor")/config.yaml`.
- Load `config.yaml` from the user config directory, with fallback to `~/.config/monitor/`.
- Load `.env` with `find_dotenv(usecwd=True)` plus user config fallbacks.

## Phase 2: Core services
6. Add `history_service.py`.
7. Add `macro_service.py`.
8. Add `status_service.py`.
9. Add `command_processor.py`.

Phase 2 is complete: the core services and command processor are implemented, including tool-calling support for multi-call extraction, envelope recording, and batched follow-up payloads using `call_id`. The tool-calling refactor is complete and now uses direct Responses API parsing from `response.output`; `parse_tool_call` and `parse_tool_calls` were removed, and current coverage verifies `extract_tool_calls`, multi-call handling, batched follow-up payloads, and `ToolTurnState` lifecycle management. `LLMRequestBuilder` and `LLMResponseClient` have been extracted into `src/monitor_oop/core/application/`, and both are covered by dedicated tests.

## Phase 3: Session and workflows
10. Add `conversation_session.py`.
11. Add `workflow.py` with orchestration functions.
12. Add `app.py` with `MonitorApp`.

Phase 3 is complete: the session/workflow layer is implemented, and the current CLI thin slice is runnable end to end in `src/monitor_oop/core/`.

## Phase 4: Server
13. Add `server_app.py`.
14. Wire the HTTP API through `RuntimeContext` only.

Phase 4 remains future work: server wiring is still pending.

## Phase 5: Thin slice
15. Make one CLI path runnable end to end.
16. Keep the first version narrow: config load, session creation, prompt, one command, exit.

The thin-slice CLI milestone is achieved in `src/monitor_oop/core/`: the first-stage flow now runs from config load through one command and exit, with OpenAI API key handling using the current environment lookup plus the `~/.config/monitor/.env` fallback.

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

## Future Work
- Complete server work.
- Add real LLM integration in a later phase.
- Expand beyond the initial CLI thin slice once the server and model-backed paths are ready.
