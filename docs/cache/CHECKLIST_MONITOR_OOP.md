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
- [x] Confirm a dedicated History domain object exists and that `HistoryService` owns it.
- [x] Define `MacroService` responsibilities.
- [x] Confirm the macro subsystem currently loads macros from the user config directory during bootstrap, seeds `MacroStore` from `macros.json.example`, and `MacroExpander` handles recursive brace expansion while delimiter/escape/TCL parity remains future work.
- [x] Define `StatusService` responsibilities.
- [x] Define `ServerApp` responsibilities.
- [x] Define the runtime object graph and ownership boundaries.
- [x] Ensure config, history, macros, and status are instance-owned.
- [x] Ensure stateful classes keep internal storage private and expose read-only or method-based access instead of public mutable fields.
- [x] Ensure any reused legacy logic is adapted through explicit inputs.
- [x] Remove fallback dependency construction from `RuntimeContext`, `LLMService`, `PromptService`, and `MacroService`.
- [x] Confirm a class-based tool registry/service with private storage for tool-calling design.
- [x] Confirm the tool subsystem uses `tool_models.py` for tool-specific dataclasses.
- [x] Confirm the concrete tool package files now exist under `src/monitor_oop/core/tools/`, including `tool_models.py`, `registry.py`, `tool_service.py`, `parsing.py`, and a sample tool module such as `weather.py`.
- [x] Confirm parsing, normalization, and output-wrapping helpers remain free functions where appropriate.
- [x] Confirm the configuration bootstrap plan preserves existing `appdirs.user_config_dir("monitor")/config.yaml` files and only seeds missing files from `src/monitor_oop/config.yaml.example`, loads `config.yaml` from the user config directory with fallback to `~/.config/monitor/`, loads `.env` with `find_dotenv(usecwd=True)` plus user config fallbacks, and keeps prompt history design in `ConversationSession` via `prompt_toolkit.PromptSession` with `FileHistory` while `ConfigService` owns resolution of the persistent history file path instead of introducing a separate `FileHistoryService`.
- [x] Confirm the system prompt is loaded from `appdirs.user_config_dir("monitor")/system_prompt`, seeded from `system_prompt.example` on first run, and injected as the first system message in LLM request construction.
- [x] Confirm prompt-specific tests or docs alignment in the OOP tracker.
- [x] Confirm prompt subsystem import-path alignment is tracked in the OOP docs and package layout.
- [x] Confirm prompt-related tests now exist.
- [x] Confirm the rules-of-thumb ownership guidance is reflected in docs/cache.
- [x] Decide which workflows remain as free functions.
- [x] Confirm conversation compaction and summarization are owned by the conversation/history layer rather than a separate global workflow.
- [x] Define the summarization service boundary and its inputs/outputs for compaction decisions.
- [x] Confirm the minimal config surface needed for compaction policy, thresholds, and history retention is tracked explicitly.

## Milestone 3: Package and bootstrap
- [x] Create the new package directory.
- [x] Add `__init__.py`.
- [x] Add startup entrypoint.
- [x] Add service modules.
- [x] Add workflow/orchestration module.
- [x] Add model/dataclass definitions.
- [x] Implement a thin-slice bootstrap that starts the app with minimal wiring.
- [x] Keep bootstrap code isolated from business logic.
- [x] Confirm current code lives under `src/monitor_oop/core/` rather than the package root.
- [x] Confirm `LoggerService` is in place for centralized logging responsibilities.
- [x] Confirm centralized logging bootstrap is in place and wired before app startup.
- [x] Confirm bootstrap ownership is strict and explicit.

## Milestone 4: Conversation flow
- [x] Implement session startup.
- [x] Implement prompt display.
- [x] Implement input collection.
- [x] Implement command classification.
- [x] Implement command execution, including tool/function calling.
- [x] Implement exit handling.
- [x] Implement token/window management.
- [x] Implement summary and history handling.
- [x] Implement multi-call handling within a single turn.
- [x] Implement follow-up payload submission using `call_id`.
- [x] Adjust test coverage to match the current service behavior for multi-call handling and follow-up payload submission.
- [x] Confirm the tool output envelope buffer was extracted into a dedicated `ToolTurnState` helper with turn-scoped lifecycle management.
- [x] Update Responses API tool-call parsing to read directly from `response.output` and remove `parse_tool_call` / `parse_tool_calls`.
- [x] Confirm the TUI transcript buffer/renderer/viewport split is implemented in the OOP app.
- [x] Confirm transcript buffering, rendering, and viewport ownership are separated across dedicated TUI components.
- [x] Confirm the TUI transcript plumbing is implemented where the conversation loop hands off transcript state to the renderer and viewport.
- [x] Confirm transcript rendering stays isolated from command processing and tool execution concerns.
- [x] Confirm viewport state is owned by the TUI layer rather than shared mutable globals.
- [x] Confirm conversation compaction decisions are owned by the history/session layer and flow through the existing turn lifecycle.
- [x] Confirm summarization output is persisted and reloaded through the history domain object without widening shared state.
- [x] Confirm the conversation loop can trigger compaction without coupling to server or tool execution paths.

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
- [x] Confirm `tests/monitor_oop/` mirrors `src/monitor_oop/` with nested `core/` and `core/tools/` subdirectories.
- [ ] Add server endpoint tests.
- [ ] Add isolation tests confirming no shared mutable state.
- [ ] Add tests confirming no legacy globals are touched.
- [ ] Compare outputs against the legacy app for critical flows.
- [ ] Add tests covering compaction trigger thresholds and summarization handoff.
- [ ] Add tests confirming summarization remains isolated to the conversation/history boundary.

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
- [x] Confirm `ConfigService` supports the fallback user config path `~/.config/monitor/.env`.
- [x] Confirm `LLMService` Responses API finish-reason handling is in place.
- [x] Confirm the 16-call defensive cap is in place for Responses API tool-calling.
- [x] Confirm the weather tool is registered at startup.
- [x] Confirm dedicated `LLMService` tests exist.
- [x] Confirm compaction-related config is minimal and intentionally scoped to the conversation/history layer.
- [x] Confirm summarization service boundaries are documented before expanding the config surface.
