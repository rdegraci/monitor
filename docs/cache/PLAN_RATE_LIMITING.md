# PLAN_RATE_LIMITING

## Goal
Document how `monitor_oop` rate limits outbound LLM requests in the current implementation, while clearly separating implemented behavior from planned work.

The current codebase uses a centralized, model-keyed rolling-window limiter in `RateLimitService`. `RateLimitService` is thread-safe and can optionally wait for budget when configured to do so. `LLMResponseClient` performs preflight checks before adapter dispatch, requires the public model-aware `record_request_for_model` method, fails fast if that method is absent, can pass through optional wait-policy values when present, and records usage after a successful send. `RequestCapacityService` remains separate and handles capacity guardrails such as context/output window checks rather than rate limiting.

The implementation is intentionally adapter-agnostic at the send boundary. Provider-specific behavior is still primarily driven through `ConfigService` and runtime configuration, but the broader provider-aware/tier-aware policy model described below is only partially implemented and should be treated as future-facing where noted.

## Current status
The current implementation includes:
- a model-keyed rolling-window `RateLimitService`
- thread-safe limiter behavior
- optional wait-for-budget behavior in `RateLimitService`
- TPM checks driven by configuration through `ConfigService`
- RPM checks where configured through `ConfigService`
- conservative fallback handling when TPM or RPM values are missing
- `LLMResponseClient` preflight enforcement before adapter dispatch
- `LLMResponseClient` model-aware request recording via the public `record_request_for_model` method
- fail-fast behavior when the public model-aware recording method is unavailable
- `LLMResponseClient` pass-through of optional wait-policy values when present
- post-send usage recording after successful requests
- separate capacity checks in `RequestCapacityService`

## Known gaps / implementation issues
- Confirmed gap: provider-aware and tier-aware limit resolution is still only partially modeled through `ConfigService` and is not a full policy engine.
- Confirmed gap: explicit config accessors or schema-backed wait policy support are still needed to make wait behavior fully first-class.
- Design choice to confirm: fallback handling for missing TPM and RPM values is conservative and should be validated as intended policy.
- Product decision needed: wait/retry behavior is not fully standardized across all call sites and workflows.
- Intentional separation: completion headroom is currently a capacity concern rather than a rate-limit concern.
- Confirmed gap: tests for waiting, rolling-window expiration, and concurrency coverage need to be expanded.
- Confirmed gap: compaction test doubles should be aligned with the real `SummarizationService` API.
- Confirmed gap: compaction triggering is currently turn-budget driven, uses an explicit threshold ratio in code, and may need to be made more explicit or token-aware.
- Confirmed gap: naming between summarization and compaction should be clarified if they are intended to be distinct.

What is not fully implemented yet:
- full provider-aware or tier-aware policy resolution
- explicit config accessors or schema-backed wait policy support
- policy validation for fallback limit values
- deeper wait/retry policy standardization across workflows
- any adapter-embedded rate limiting logic

## Current Direction
The intended design remains a shared runtime service that enforces token-based limits across providers, and that design is already reflected in the current preflight/recording path. The current implementation should be described in terms of what it actually does today:
- `RateLimitService` owns rolling-window accounting, limit evaluation, and optional waiting behavior
- `ConfigService` provides model/config data used to determine the effective limits currently in use
- `LLMResponseClient` calls the limiter before invoking the adapter and requires the public model-aware record path, failing fast if it is not available
- provider adapters remain transport-only and do not embed rate limiting logic
- future provider adapters should reuse the same limiter through the same service boundary

The schema-backed runtime config source is `RuntimeConfig` via `config_loader`, with the current greenfield rate-limit and config schema living in `src/monitor_oop/model_config_v2.json`.

The limiter currently enforces token-per-minute behavior and may also enforce request-per-minute behavior when configured. This should be described as implemented behavior, not as a future design choice.

`context_window_mapping` and `output_window_mapping` are capacity guardrails, not the rate limit itself. Context windows determine whether the request fits, output windows determine completion headroom, and TPM/RPM enforcement remains the time-based usage budget. Compaction is a separate capacity-management concern driven by context-window pressure; when a request needs resizing, compaction should occur before rate-limit preflight. The current code path preserves this separation by checking capacity first, then applying rate limiting, and only then dispatching to the adapter.

## Guiding Principles
- Centralize all LLM send-path rate limiting in one service.
- Keep provider-specific knowledge in configuration where possible, rather than in adapter code.
- Estimate tokens before each request using the full payload, not just the latest user message.
- Record usage only after the request is approved and sent.
- Make the policy easy to test in isolation.
- Keep the design compatible with LiteLLM-based provider adapters.
- Make any wait-or-fail behavior explicit when it is implemented, rather than implied.

## Proposed Runtime Flow
1. Build the request payload.
2. Estimate the token cost for the full payload.
3. Determine provider and model from runtime config.
4. Ask `RateLimitService` whether the request may proceed.
5. If the request is blocked, return a clear error or retry according to the configured behavior, where supported.
6. Dispatch the request through the adapter.
7. Record the actual or estimated usage after dispatch.
8. Repeat the same flow for any follow-up tool calls or summarization requests.

## Policy Model
The implemented policy is primarily token-based:
- track a rolling window of token usage
- enforce TPM based on configuration
- enforce RPM when configured
- keep the evaluation deterministic and per-request

Some of the broader policy concepts below are still partially implemented or planned:
- provider-aware limit selection
- model-aware tier resolution
- safety-factor policy as a distinct abstraction
- completion reserve as a rate-limit input
- separate tracking for primary versus follow-up requests

Suggested precedence for effective limits, where available in configuration:
1. exact model limit
2. provider-level limit
3. global default limit
4. disabled rate limiting when no usable limit exists

### Recommended Initial Policies
- Enforce TPM by default.
- Keep RPM optional and off by default where the configuration does not define it.
- Treat completion headroom as a capacity concern unless and until it is explicitly part of rate-limit policy.
- Prefer explicit, deterministic failure behavior unless a wait/retry policy is added later.
- Keep server-mode behavior and CLI/TUI behavior configurable if wait logic is introduced in the future.

## Config Surface
The config surface should stay small but extensible:
- `rate_limiting.enabled`
- `rate_limiting.window_seconds`
- `rate_limiting.safety_factor`
- `rate_limiting.default_tpm`
- provider-specific TPM ceilings, keyed by provider name
- optional model-specific TPM ceilings, keyed by model name
- optional completion reserve settings for headroom
- optional wait-vs-fail policy selection

The config is loaded through `RuntimeConfig` and `config_loader`, backed by `src/monitor_oop/model_config_v2.json`, rather than embedded in adapters or free functions.

## Canonical Future Loader Schema
The recommended canonical schema for the future loader is an explicit model-to-provider-to-tier resolution format using `provider_table/tier_key`. See `docs/cache/PLAN_MODEL_CONFIG_V2.md` for the schema contract; `RateLimitService` can use that contract if and when the loader fully supports it.

In that schema:
- `model` resolves to a provider entry in `provider_table`
- the provider entry selects a `tier_key`
- the `tier_key` resolves to the effective rate-limit and budget policy
- the resulting structure keeps model, provider, and tier concerns separable while still being deterministic

This format should be treated as the preferred path for the `model_config_v2.json` loader so the rate-limit service can resolve limits without embedding provider logic in adapters.

## Adapter Boundary
The adapters should not know how rate limiting works internally.

Expected boundaries:
- `LLMResponseClient` gathers context and invokes the limiter.
- `ResponsesOpenAiAdapter` sends the request and returns the provider response.
- The future Anthropic LiteLLM adapter will follow the same contract.
- Any provider-specific retry or follow-up behavior should still go through the same limiter before each dispatch.

This keeps the transport layer simple and makes future provider support predictable.

## Accounting Model
The limiter treats each send as a reservation and then a commit:
- preflight: estimate cost and check budget
- commit: record the request once it is sent
- adjust: if actual usage is known later, update the rolling accounting accordingly

The limiter should account for:
- system prompt and instructions
- user prompt
- conversation history
- tool schemas if they materially affect payload size
- tool outputs returned to the model
- summary prompts and follow-up requests
- a completion reserve when appropriate, if that policy is enabled in the future

## Rolling Window Strategy
Use a rolling-window structure keyed by provider and model where applicable:
- store timestamped token events
- purge events older than `window_seconds`
- compute current usage on demand
- avoid mutable module globals

For a single-process desktop or CLI app, an in-memory deque-based implementation is sufficient. If multi-process support is needed later, the service can be backed by Redis or another shared store without changing the public API.

## Recommendations for OOP Integration
For `monitor_oop`, the most maintainable plan is:
- keep `rate_limit_service.py` under `core/infrastructure/`
- inject it into `LLMResponseClient`
- have `LLMResponseClient.create_response(...)` call it before every adapter invocation
- keep provider/model resolution in `ConfigService`
- keep token estimation in a shared utility or service
- wire the same limiter into future Anthropic/LiteLLM request paths

## Verification Focus
Any implementation should be verified for:
- preflight rate checks before every LLM send
- correct provider/model resolution where supported by config
- consistent token estimates across normal, follow-up, summary, and retry paths
- safety-factor application where configured
- rolling-window expiration behavior
- correct commit behavior after successful dispatch
- no duplicate enforcement inside adapters
- compatibility with a future Anthropic LiteLLM adapter

## Remaining work
- Expand provider-aware and tier-aware limit resolution if the config schema requires it.
- Add explicit config accessors or schema-backed wait policy support if wait behavior needs to be fully first-class.
- Validate fallback handling for missing TPM and RPM values as part of policy definition.
- Add explicit wait/retry semantics if interactive or server workflows need them.
- Improve observability for effective limits, blocked requests, and usage adjustments.
- Extend tests to cover waiting, rolling-window expiration, concurrency, follow-up, summary, and retry paths across all supported providers.
- Align compaction test doubles with the real `SummarizationService` API.
- Clarify whether compaction triggering should remain turn-budget driven and use an explicit threshold ratio in code, or become more explicit or token-aware.
- Separate summarization and compaction naming and roles if they are intended to be distinct.

## Notes
- Prefer a single shared enforcement point over scattered checks.
- Keep the first version deterministic and well instrumented.
- If waiting is supported later, make the timeout and behavior explicit.
- Log the effective provider/model limit and the reason a request was delayed or blocked.
- The design should remain easy to expand as more providers are added.
