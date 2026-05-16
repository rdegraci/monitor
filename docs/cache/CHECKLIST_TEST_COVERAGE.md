# Test Coverage Checklist

## Uncovered modules
- [ ] `src/monitor_oop/core/application/llm_request_builder.py`
- [ ] `src/monitor_oop/core/config_accessor_service.py`
- [ ] `src/monitor_oop/core/config_path_context.py`
- [ ] `src/monitor_oop/core/config_path_service.py`
- [ ] `src/monitor_oop/core/config_resolution_service.py`
- [ ] `src/monitor_oop/core/infrastructure/env_loader.py`
- [ ] `src/monitor_oop/core/infrastructure/llm_response_client.py`
- [ ] `src/monitor_oop/core/infrastructure/rate_limit_service.py`
- [ ] `src/monitor_oop/core/infrastructure/request_capacity_service.py`
- [ ] `src/monitor_oop/core/llm_adapter.py`
- [ ] `src/monitor_oop/core/logger_service.py`
- [ ] `src/monitor_oop/core/resolved_runtime_config.py`
- [ ] `src/monitor_oop/core/turn_budget.py`
- [ ] `src/monitor_oop/core/workflow.py`
- [ ] `src/monitor_oop/core/presentation/events.py`
- [ ] `src/monitor_oop/core/presentation/layout.py`
- [ ] `src/monitor_oop/core/presentation/transcript_buffer.py`
- [ ] `src/monitor_oop/core/presentation/transcript_viewport.py`
- [ ] `src/monitor_oop/core/presentation/tui.py`
- [ ] `src/monitor_oop/core/tools/registry.py`
- [ ] `src/monitor_oop/core/tools/tool_models.py`
- [ ] `src/monitor_oop/core/tools/tool_service.py`

## Immediate test opportunities
- [ ] Add service tests for request capacity decisions
- [ ] Add rate limit rolling-window tests
- [ ] Add LLM response client preflight tests
- [ ] Add config resolution override tests
- [ ] Add tool registry and tool service behavior tests

## Already improved or partially covered
- [x] `src/monitor_oop/core/presentation/transcript_viewport.py` transcript viewport tests completed; stale assumptions were updated to match the current implementation.
- [x] `src/monitor_oop/core/presentation/tui.py` transcript plumbing tests completed; stale assumptions were updated to match the current implementation.
- [x] `src/monitor_oop/core/__init__.py` does not require dedicated coverage
- [x] Core service boundaries have been encapsulation-refactored in preparation for new tests, including config resolution, request capacity, rate limit, response client, tool service, config path, env loader, config accessor, turn budget, and logger service.
- [x] The remaining presentation and utility modules have been encapsulation-refactored in preparation for tests, specifically llm_request_builder, llm_adapter, events, layout, transcript_buffer, tui, resolved_runtime_config, config_path_context, registry, tool_models, and workflow.
