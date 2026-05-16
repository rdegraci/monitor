# Test Coverage Plan

## Goal
Improve direct test coverage for the currently uncovered `src/monitor_oop/core` modules.

The test suite should be deterministic, isolated, and non-brittle, avoiding timing dependence and implementation-detail coupling. For request capacity hardening, prefer durable behavior-focused assertions over internal math checks, and use clearly oversized inputs instead of borderline token estimates.

## Current refactor progress
The next test-ready targets now include the refactored service boundaries. The following areas have been encapsulated to support upcoming tests: config resolution, request capacity, rate limiting, response client, tool service, config path, env loader, config accessor, turn budget, and logger service. Additional presentation and utility modules have also been encapsulation-refactored so test expansion can focus on clearer boundaries: llm_request_builder, llm_adapter, events, layout, transcript_buffer, tui, resolved_runtime_config, config_path_context, registry, tool_models, and workflow. Request capacity and rate limit tests now emphasize durable behavior over brittle boundary math, and LLM response client rejection-path coverage asserts the collaborator is invoked, the adapter is not called, and a clear error is raised. First-pass service coverage has landed for config resolution, tool service, request capacity, rate limiting, and response client behavior.

## High-priority targets
1. `src/monitor_oop/core/config_path_service.py`
2. `src/monitor_oop/core/infrastructure/env_loader.py`

## Secondary targets
1. `src/monitor_oop/core/config_accessor_service.py`
2. `src/monitor_oop/core/turn_budget.py`
3. `src/monitor_oop/core/logger_service.py`

## Lower-priority targets
1. `src/monitor_oop/core/presentation/events.py`
2. `src/monitor_oop/core/presentation/layout.py`
3. `src/monitor_oop/core/presentation/transcript_buffer.py`
4. `src/monitor_oop/core/presentation/tui.py`
5. `src/monitor_oop/core/application/llm_request_builder.py`
6. `src/monitor_oop/core/llm_adapter.py`
7. `src/monitor_oop/core/resolved_runtime_config.py`
8. `src/monitor_oop/core/workflow.py`

## Suggested first pass
Start with boundary-heavy services because they provide the most coverage value per test:
- config resolution
- tool execution

## Notes
- `src/monitor_oop/core/__init__.py` does not need explicit coverage if it only re-exports symbols.
- The transcript viewport and Tui transcript plumbing tests have already been refreshed and are no longer part of the immediate gap list.
- The new transcript viewport tests already reduce some of the remaining presentation gap.
- Request capacity coverage has been expanded with durable assertions: clearly oversized failures, near-limit fits with headroom, and structured result validation without exact internal math.
