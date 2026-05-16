# CHECKLIST_RATELIMITING

## Goal
Track the work needed to add centralized, provider-aware LLM rate limiting to `monitor_oop`.

This tracker assumes the limiter will be shared by the current OpenAI path and the upcoming Anthropic path that will use a LiteLLM-backed Responses API adapter.

## Implementation reality
`RequestCapacityService` handles capacity checks separately from rate limiting; capacity preflight runs before rate-limit preflight when a request needs resizing due to context-window pressure.

## Scope
This tracker covers:
- centralized request gating before every LLM send
- provider/model-aware token budgets
- rolling-window accounting
- completion headroom reservation
- integration into the OOP response client
- future LiteLLM/Anthropic compatibility
- verification of wait or fail behavior
- context windows and output windows as capacity guardrails, not the rate limit itself
- use of context/output windows only for fit checks and completion headroom in the rate-limiting implementation
- compaction kept separate from rate limiting, while allowing compaction to run before rate-limit preflight when a request needs resizing due to context-window pressure
- first-implementation slice includes `RequestCapacityService`, `RateLimitService`, and `LLMResponseClient` preflight orchestration
- capacity is checked before rate limiting and adapter dispatch

## Known gaps / bugs to address
- [ ] Confirmed gap: provider-aware and tier-aware resolution is correct for the initial implementation path.
- [x] Conservative fallback handling is implemented for the current provider/model resolution path.
- [ ] Design choice to confirm: TPM fallback-to-1 behavior is safe for production defaults.
- [ ] Confirmed gap: reconcile the asymmetry between TPM missing-value behavior and RPM missing-value behavior.
- [ ] Design choice to confirm: wait/retry behavior should be added now or deferred to a later iteration.
- [x] Optional waiting support is partially implemented in the current preflight flow.
- [ ] Design choice to confirm: completion headroom should remain explicitly separate from rate limiting or be intentionally folded into the limiter.
- [x] Confirmed gap: evaluate thread-safety and concurrency protection for the rolling-window state.

## Milestone 1: Policy definition
- [x] Define rate limiting as a pre-send check rather than an adapter concern.
- [x] Define the limiter as provider-aware and model-aware.
- [x] Define token-per-minute enforcement as the primary mechanism.
- [ ] Define request-per-minute enforcement as optional future work.
- [ ] Define safety-factor application against provider ceilings.
- [x] Define a single shared enforcement point for all LLM calls.
- [x] Make TPM enforcement mandatory in the initial policy.
- [ ] Keep RPM enforcement optional and off by default in the initial policy.
- [ ] Enable completion headroom by default with a configurable factor and floor.
- [ ] Set wait-then-fail as the default interactive policy.
- [ ] Define server-mode behavior as fail-fast or short-wait.
- [x] Confirm context windows and output windows are treated as capacity guardrails, not the rate limit itself.
- [x] Confirm the rate-limiting implementation uses context windows and output windows only for fit checks and completion headroom.
- [x] Confirm compaction remains separate from rate limiting, while allowing compaction to run before rate-limit preflight when a request needs resizing due to context-window pressure.

## Milestone 2: Runtime placement
- [x] Place rate limiting in a shared infrastructure service.
- [x] Define `LLMResponseClient` as the call-site that invokes the limiter.
- [x] Define adapters as transport-only and rate-limit agnostic.
- [x] Define compatibility with future Anthropic LiteLLM request flow.
- [x] Define how tool follow-ups and summarization requests reuse the same limiter.

## Milestone 3: Accounting model
- [x] Define preflight token estimation from the full payload.
- [x] Define commit behavior after the request is dispatched.
- [x] Define rolling-window accounting keyed by provider and model.
- [x] Define headroom reservation for completion and retries.
- [x] Define expiration of old usage events from the rolling window.
- [x] Define logging for delayed or blocked requests.

## Milestone 4: Configuration
- [ ] Add config keys for rate limiting enablement.
- [ ] Add config keys for rolling-window length.
- [ ] Add config keys for safety factor.
- [ ] Add config keys for global default TPM.
- [ ] Add config keys for provider-level TPM ceilings.
- [ ] Add config keys for model-level TPM ceilings.
- [ ] Add config keys for wait-vs-fail behavior.
- [ ] Add config keys for optional completion reserve.
- [ ] Confirm `model_config_v2.json` is treated as the greenfield canonical schema.
- [ ] Document the `provider_table/tier_key` tier-reference format.
- [ ] Reference `docs/cache/CHECKLIST_MODEL_CONFIG_V2.md` as the schema tracker this rate-limiting work depends on.
- [ ] Implement loader and validation behavior to match the canonical schema.

## Milestone 5: Implementation
- [x] Add a dedicated rate limiting service module.
- [x] Add token estimation support or reuse a shared estimator.
- [x] Inject the limiter into `LLMResponseClient`.
- [x] Call the limiter before every adapter invocation.
- [x] Record usage after successful dispatch.
- [x] Ensure follow-up tool calls and summary calls use the same path.
- [x] Ensure the future Anthropic adapter can reuse the same service contract.
- [x] Add thread-safety protections for the rolling-window state.
- [x] Add conservative fallback handling for missing or partial policy values.
- [ ] Add explicit config accessors for wait-policy and fallback-resolution behavior.
- [ ] Add schema-backed wait policy support.
- [ ] Validate fallback values against policy constraints before use.
- [ ] Expand provider/tier policy resolution beyond the current implementation path.

## Milestone 6: Verification
- [ ] Add tests for preflight approval and rejection.
- [ ] Add tests for wait behavior when enabled.
- [ ] Add tests for rolling-window expiration.
- [ ] Add tests for provider/model limit selection.
- [ ] Add tests for safety-factor application.
- [ ] Add tests for follow-up and summarization request coverage.
- [ ] Add tests for compatibility with a future LiteLLM-backed Anthropic adapter.
- [ ] Add tests confirming adapters remain transport-only.
- [ ] Add tests for thread safety and concurrent rate-limit updates.
- [ ] Add tests for fallback handling and policy validation.
- [ ] Add tests for explicit wait-policy config accessors and schema-backed wait support.

## Notes
- Prefer a deterministic first implementation.
- Keep the limiter easy to test without network access.
- Avoid duplicating token accounting logic in multiple layers.
- Log the effective budget and the reason for any blocking decision.
- Keep the public service interface stable so provider support can expand later without refactoring call sites.
