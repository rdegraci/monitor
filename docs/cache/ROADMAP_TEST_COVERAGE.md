# Test Coverage Roadmap

## Phase 1: critical service coverage
Focus on the most logic-heavy and failure-prone modules first. The service-boundary refactors are complete, and the current test work is centered on durable behavior at the edges rather than brittle internal math, timing, or implementation details. Coverage has landed for config resolution, request capacity, rate limiting, response client, logger service, and tool service tests, so the remaining effort is concentrated on the still-open service boundaries.

- `src/monitor_oop/core/infrastructure/llm_response_client.py`

## Phase 2: configuration and runtime support
After the service boundaries are covered, test runtime glue and file/path helpers. The refactored modules in this phase also have cleaner boundaries for future coverage work, and the remaining OOP infrastructure boundaries are the main focus now.

- `src/monitor_oop/core/config_path_service.py`
- `src/monitor_oop/core/infrastructure/env_loader.py`
- `src/monitor_oop/core/config_accessor_service.py`
- `src/monitor_oop/core/turn_budget.py`
- `src/monitor_oop/core/logger_service.py`

## Phase 3: presentation and orchestration
These modules are the main remaining focus and are useful to cover once the core logic is stabilized. The presentation and utility modules now have cleaner boundaries, especially the orchestration and transcript plumbing modules, which should make targeted test expansion easier.

- `src/monitor_oop/core/presentation/events.py`
- `src/monitor_oop/core/presentation/layout.py`
- `src/monitor_oop/core/presentation/transcript_buffer.py`
- `src/monitor_oop/core/presentation/transcript_viewport.py` — refreshed successfully.
- `src/monitor_oop/core/presentation/tui.py` — refreshed successfully; transcript plumbing is already completed.
- `src/monitor_oop/core/application/llm_request_builder.py`
- `src/monitor_oop/core/llm_adapter.py`
- `src/monitor_oop/core/resolved_runtime_config.py`
- `src/monitor_oop/core/workflow.py`

## Phase 4: finish remaining gaps
Use this phase to close out small data and registry modules. These utility modules now also have cleaner boundaries, which should help keep the remaining coverage work focused and low risk.

- `src/monitor_oop/core/config_path_context.py`
- `src/monitor_oop/core/tools/registry.py`
- `src/monitor_oop/core/tools/tool_models.py`

## Success criteria
- Every high-priority service has direct tests.
- Coverage gaps are limited to trivial dataclasses or thin wrappers.
- New tests are stable, deterministic, and isolated from network access.
