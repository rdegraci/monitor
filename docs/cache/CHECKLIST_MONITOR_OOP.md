# CHECKLIST_MONITOR_OOP

## Tracking Documents
- [x] Confirm `PLAN_MONITOR_OOP.md` is current and used for planning decisions.
- [x] Confirm `MONITOR_OOP_CLASS_MAP.md` is current and used for class and responsibility mapping.
- [x] Confirm `MONITOR_OOP_IMPLEMENTATION_SEQUENCE.md` is current and used for implementation ordering.
- [x] Confirm `MONITOR_OOP_VERIFICATION_PLAN.md` is current and used as the verification reference.
- [x] Confirm the first-pass class map and build sequence stay in sync with this tracker.

## Milestone 1: Scope and separation
- [x] Confirm the new app package name and directory.
- [x] Confirm the new package is separate from legacy code paths.
- [x] Confirm the new app will not import, read, or mutate legacy runtime globals.
- [x] Confirm startup modes to support: CLI, script, server.
- [ ] Confirm which legacy behaviors must be preserved exactly.

## Milestone 2: Runtime object graph
- [x] Define `MonitorApp` responsibilities.
- [x] Define `RuntimeContext` responsibilities.
- [x] Define `ConfigService` responsibilities.
- [x] Define `ConversationSession` responsibilities.
- [x] Define `CommandProcessor` responsibilities.
- [x] Define `HistoryService` responsibilities.
- [x] Define `MacroService` responsibilities.
- [x] Define `StatusService` responsibilities.
- [x] Define `ServerApp` responsibilities.
- [x] Define the runtime object graph and ownership boundaries.
- [x] Ensure config, history, macros, and status are instance-owned.
- [x] Ensure any reused legacy logic is adapted through explicit inputs.
- [ ] Decide which workflows remain as free functions.

## Milestone 3: Package and bootstrap
- [x] Create the new package directory.
- [x] Add `__init__.py`.
- [x] Add startup entrypoint.
- [x] Add service modules.
- [x] Add workflow/orchestration module.
- [x] Add model/dataclass definitions.
- [x] Implement a thin-slice bootstrap that starts the app with minimal wiring.
- [x] Keep bootstrap code isolated from business logic.

## Milestone 4: Conversation flow
- [x] Implement session startup.
- [x] Implement prompt display.
- [x] Implement input collection.
- [x] Implement command classification.
- [ ] Implement command execution.
- [x] Implement exit handling.
- [ ] Implement token/window management.
- [ ] Implement summary and history handling.

## Milestone 5: Server flow
- [ ] Implement isolated Flask app creation.
- [ ] Implement request-to-command conversion.
- [ ] Implement command execution through new app services.
- [ ] Implement streaming response support if needed.
- [ ] Implement API key enforcement if needed.

## Milestone 6: Verification and isolation
- [x] Add startup tests for the new app.
- [x] Add command processing tests.
- [x] Add conversation loop tests.
- [ ] Add server endpoint tests.
- [ ] Add isolation tests confirming no shared mutable state.
- [ ] Add tests confirming no legacy globals are touched.
- [ ] Compare outputs against the legacy app for critical flows.

## Milestone 7: Migration control
- [x] Keep the legacy app unchanged during initial development.
- [x] Avoid refactoring legacy code until the new app is stable.
- [ ] Document differences intentionally introduced in the new app.
- [ ] Decide on cutover only after validation succeeds.

## Starter Blueprint Checks
- [x] Confirm the recommended package layout exists before adding behavior.
- [x] Confirm the runtime object graph is explicit and owned by the app instance.
- [x] Confirm startup order is bootstrap -> config -> services -> session/server -> command loop.
- [x] Confirm the first implementation is a thin slice that can start and stop cleanly.
- [x] Confirm early avoidance items are in place: no legacy globals, no hidden shared state, no broad refactors, no cross-package coupling.
- [x] Confirm the first file order is package init, model/dataclasses, services, orchestration, startup entrypoint, tests.
- [x] Confirm each checklist item is actionable enough to track implementation progress.
- [x] Confirm this section is used as the initial blueprint tracker for the new app.
