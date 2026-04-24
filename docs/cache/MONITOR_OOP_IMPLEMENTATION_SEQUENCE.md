# MONITOR_OOP_IMPLEMENTATION_SEQUENCE

## Phase 1: Foundation
1. Create `src/monitor_oop/`.
2. Add `__init__.py`.
3. Add `models.py` with enums and dataclasses.
4. Add `context.py` with `RuntimeContext`.
5. Add `config_service.py`.

## Phase 2: Core services
6. Add `history_service.py`.
7. Add `macro_service.py`.
8. Add `status_service.py`.
9. Add `command_processor.py`.

## Phase 3: Session and workflows
10. Add `conversation_session.py`.
11. Add `workflow.py` with orchestration functions.
12. Add `app.py` with `MonitorApp`.

## Phase 4: Server
13. Add `server_app.py`.
14. Wire the HTTP API through `RuntimeContext` only.

## Phase 5: Thin slice
15. Make one CLI path runnable end to end.
16. Keep the first version narrow: config load, session creation, prompt, one command, exit.

## Phase 6: Tests
17. Add startup tests.
18. Add config service tests.
19. Add command processor tests.
20. Add conversation session tests.
21. Add server tests.
22. Add isolation tests that confirm no legacy globals are touched.

## Implementation Notes
- Prefer small constructors with explicit dependencies.
- Use free functions only for orchestration.
- Keep shared helpers pure where possible.
- Avoid introducing circular imports between services.
- Keep the legacy app unchanged during this sequence.
