# CHECKLIST_MONITOR_OOP

## Tracking Documents
- [ ] Confirm `PLAN_MONITOR_OOP.md` is current and used for planning decisions.
- [ ] Confirm `MONITOR_OOP_CLASS_MAP.md` is current and used for class and responsibility mapping.
- [ ] Confirm `MONITOR_OOP_IMPLEMENTATION_SEQUENCE.md` is current and used for implementation ordering.
- [ ] Confirm `MONITOR_OOP_VERIFICATION_PLAN.md` is current and used as the verification reference.
- [ ] Confirm the first-pass class map and build sequence stay in sync with this tracker.

## Milestone 1: Scope and separation
- [ ] Confirm the new app package name and directory.
- [ ] Confirm the new package is separate from legacy code paths.
- [ ] Confirm the new app will not import, read, or mutate legacy runtime globals.
- [ ] Confirm startup modes to support: CLI, script, server.
- [ ] Confirm which legacy behaviors must be preserved exactly.

## Milestone 2: Runtime object graph
- [ ] Define `MonitorApp` responsibilities.
- [ ] Define `RuntimeContext` responsibilities.
- [ ] Define `ConfigService` responsibilities.
- [ ] Define `ConversationSession` responsibilities.
- [ ] Define `CommandProcessor` responsibilities.
- [ ] Define `HistoryService` responsibilities.
- [ ] Define `MacroService` responsibilities.
- [ ] Define `StatusService` responsibilities.
- [ ] Define `ServerApp` responsibilities.
- [ ] Define the runtime object graph and ownership boundaries.
- [ ] Ensure config, history, macros, and status are instance-owned.
- [ ] Ensure any reused legacy logic is adapted through explicit inputs.
- [ ] Decide which workflows remain as free functions.

## Milestone 3: Package and bootstrap
- [ ] Create the new package directory.
- [ ] Add `__init__.py`.
- [ ] Add startup entrypoint.
- [ ] Add service modules.
- [ ] Add workflow/orchestration module.
- [ ] Add model/dataclass definitions.
- [ ] Implement a thin-slice bootstrap that starts the app with minimal wiring.
- [ ] Keep bootstrap code isolated from business logic.

## Milestone 4: Conversation flow
- [ ] Implement session startup.
- [ ] Implement prompt display.
- [ ] Implement input collection.
- [ ] Implement command classification.
- [ ] Implement command execution.
- [ ] Implement exit handling.
- [ ] Implement token/window management.
- [ ] Implement summary and history handling.

## Milestone 5: Server flow
- [ ] Implement isolated Flask app creation.
- [ ] Implement request-to-command conversion.
- [ ] Implement command execution through new app services.
- [ ] Implement streaming response support if needed.
- [ ] Implement API key enforcement if needed.

## Milestone 6: Verification and isolation
- [ ] Add startup tests for the new app.
- [ ] Add command processing tests.
- [ ] Add conversation loop tests.
- [ ] Add server endpoint tests.
- [ ] Add isolation tests confirming no shared mutable state.
- [ ] Add tests confirming no legacy globals are touched.
- [ ] Compare outputs against the legacy app for critical flows.

## Milestone 7: Migration control
- [ ] Keep the legacy app unchanged during initial development.
- [ ] Avoid refactoring legacy code until the new app is stable.
- [ ] Document differences intentionally introduced in the new app.
- [ ] Decide on cutover only after validation succeeds.

## Starter Blueprint Checks
- [ ] Confirm the recommended package layout exists before adding behavior.
- [ ] Confirm the runtime object graph is explicit and owned by the app instance.
- [ ] Confirm startup order is bootstrap -> config -> services -> session/server -> command loop.
- [ ] Confirm the first implementation is a thin slice that can start and stop cleanly.
- [ ] Confirm early avoidance items are in place: no legacy globals, no hidden shared state, no broad refactors, no cross-package coupling.
- [ ] Confirm the first file order is package init, model/dataclasses, services, orchestration, startup entrypoint, tests.
- [ ] Confirm each checklist item is actionable enough to track implementation progress.
- [ ] Confirm this section is used as the initial blueprint tracker for the new app.
