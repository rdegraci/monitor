# Test Coverage Plan

## Goal
Improve direct test coverage for the currently uncovered `src/monitor_oop/core` modules.

The test suite should be deterministic, isolated, and non-brittle, avoiding timing dependence and implementation-detail coupling. For request capacity hardening, prefer durable behavior-focused assertions over internal math checks, and use clearly oversized inputs instead of borderline token estimates.

## Current refactor progress
The next test-ready targets now include the refactored service boundaries. The following areas have been encapsulated to support upcoming tests: config resolution, request capacity, rate limiting, response client, tool service, config path, env loader, config accessor, turn budget, and logger service. Additional presentation and utility modules have also been encapsulation-refactored so test expansion can focus on clearer boundaries: events, layout, transcript_buffer, transcript_viewport, tui, config_path_context, registry, tool_models, and workflow. Request capacity and rate limit tests now emphasize durable behavior over brittle boundary math, and LLM response client rejection-path coverage asserts the collaborator is invoked, the adapter is not called, and a clear error is raised. First-pass service coverage has landed for config resolution, tool service, request capacity_service, rate limiting, config path, env loader, config accessor, turn budget, response client behavior, logger service, and llm_request_builder. Direct tests have now also landed for resolved_runtime_config, config_path_context, llm_adapter, tools/registry, presentation/layout, presentation/transcript_buffer, presentation/transcript_viewport, and workflow.

## Coverage status
The listed core modules are now covered. Any remaining gap is limited to trivial wrappers or newly discovered modules that are not yet part of the current test sweep.
