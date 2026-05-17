# Test Coverage Checklist

## Uncovered modules
- [x] `src/monitor_oop/core/application/llm_request_builder.py`
- [x] `src/monitor_oop/core/config_accessor_service.py`
- [x] `src/monitor_oop/core/config_path_context.py`
- [x] `src/monitor_oop/core/config_path_service.py`
- [x] `src/monitor_oop/core/config_resolution_service.py`
- [x] `src/monitor_oop/core/infrastructure/env_loader.py`
- [x] `src/monitor_oop/core/infrastructure/llm_response_client.py`
- [x] `src/monitor_oop/core/infrastructure/rate_limit_service.py`
- [x] `src/monitor_oop/core/infrastructure/request_capacity_service.py`
- [x] `src/monitor_oop/core/llm_adapter.py`
- [x] `src/monitor_oop/core/logger_service.py`
- [x] `src/monitor_oop/core/resolved_runtime_config.py`
- [x] `src/monitor_oop/core/turn_budget.py`
- [x] `src/monitor_oop/core/workflow.py`
- [x] `src/monitor_oop/core/presentation/events.py`
- [x] `src/monitor_oop/core/presentation/layout.py`
- [x] `src/monitor_oop/core/presentation/transcript_buffer.py`
- [x] `src/monitor_oop/core/presentation/transcript_viewport.py`
- [x] `src/monitor_oop/core/presentation/tui.py`
- [x] `src/monitor_oop/core/tools/registry.py`
- [x] `src/monitor_oop/core/tools/tool_models.py`
- [x] `src/monitor_oop/core/tools/tool_service.py`

## Immediate test opportunities
- [x] Add service tests for request capacity decisions, with durable assertions around behavior and outcomes rather than brittle boundary math.
- [x] Add rate limit rolling-window tests, focusing on observable throttling behavior instead of timing-sensitive internals.
- [x] Add LLM response client preflight tests, covering in-progress response handling and stable decision paths.
- [x] Add config resolution override tests
- [x] Add tool registry and tool service behavior tests

## Already improved or partially covered
- [x] `src/monitor_oop/core/presentation/transcript_viewport.py` transcript viewport tests completed; stale assumptions were updated to match the current implementation.
- [x] `src/monitor_oop/core/presentation/tui.py` transcript plumbing tests completed; stale assumptions were updated to match the current implementation.
- [x] `src/monitor_oop/core/__init__.py` does not require dedicated coverage
- [x] Core service boundaries have been encapsulation-refactored in preparation for durable tests, including config resolution, request capacity, rate limit, response client, tool service, config path, env loader, config accessor, turn budget, and logger service.
- [x] The remaining presentation and utility modules have been encapsulation-refactored in preparation for tests, specifically llm_request_builder, llm_adapter, events, layout, transcript_buffer, tui, resolved_runtime_config, config_path_context, registry, tool_models, and workflow.
