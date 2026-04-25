# MONITOR_OOP_IMPLEMENTATION_SEQUENCE

## Phase 1: Foundation
1. Create `src/monitor_oop/`.
2. Add `__init__.py`.
3. Add `models.py` with enums and dataclasses.
4. Add `context.py` with `RuntimeContext`.
5. Add `config_service.py`.

Phase 1 is complete: the foundation package, models, runtime context, and config service are in place.

## Phase 2: Core services
6. Add `history_service.py`.
7. Add `macro_service.py`.
8. Add `status_service.py`.
9. Add `command_processor.py`.

Phase 2 is complete: the core services and command processor are implemented.

## Phase 3: Session and workflows
10. Add `conversation_session.py`.
11. Add `workflow.py` with orchestration functions.
12. Add `app.py` with `MonitorApp`.

Phase 3 is complete: the session/workflow layer is implemented, and the current CLI loop is runnable end to end.

## Phase 4: Server
13. Add `server_app.py`.
14. Wire the HTTP API through `RuntimeContext` only.

Phase 4 remains future work: server wiring is still pending.

## Phase 5: Thin slice
15. Make one CLI path runnable end to end.
16. Keep the first version narrow: config load, session creation, prompt, one command, exit.

The thin-slice CLI milestone is achieved: the first-stage flow now runs from config load through one command and exit.

## Phase 6: Tests
17. Add startup tests.
18. Add config service tests.
19. Add command processor tests.
20. Add conversation session tests.
21. Add server tests.
22. Add isolation tests that confirm no legacy globals are touched.

The new tests cover the first-stage flow, including startup, config service, command processor, conversation session, and isolation coverage.

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
