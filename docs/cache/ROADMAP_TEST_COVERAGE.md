# Test Coverage Roadmap

## Status
The current gap list has been swept and the listed core modules are now covered. Any remaining coverage work is limited to trivial wrappers or newly discovered modules that were not part of the current pass.

## Remaining work
- `src/monitor_oop/core/infrastructure/llm_response_client.py`
- `src/monitor_oop/core/config_path_service.py`
- `src/monitor_oop/core/infrastructure/env_loader.py`
- `src/monitor_oop/core/config_accessor_service.py`
- `src/monitor_oop/core/turn_budget.py`
- `src/monitor_oop/core/logger_service.py`
- `src/monitor_oop/core/presentation/events.py`
- `src/monitor_oop/core/presentation/tui.py`
- `src/monitor_oop/core/tools/tool_models.py`

## Success criteria
- Every high-priority service has direct tests.
- Coverage gaps are limited to trivial dataclasses or thin wrappers.
- New tests are stable, deterministic, and isolated from network access.
