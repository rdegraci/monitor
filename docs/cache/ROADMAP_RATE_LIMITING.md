# ROADMAP_RATE_LIMITING

## Purpose
This roadmap summarizes how the rate-limiting subsystem in `monitor_oop` has evolved, what is implemented today, and what remains to be done.

It is intended as a narrative companion to:
- `docs/cache/PLAN_RATE_LIMITING.md`
- `docs/cache/CHECKLIST_RATELIMITING.md`

## Where we have been
The rate-limiting work began with a broader design goal: centralize LLM send-path enforcement so the app could gate outbound requests before dispatch, keep provider logic out of adapters, and preserve a deterministic accounting model.

The initial design direction emphasized:
- a shared limiter service
- token-based enforcement as the primary control
- compatibility with a future LiteLLM-backed provider path
- separation between capacity checks and rate limiting
- rolling-window accounting rather than a fixed bucket model

As the OOP refactor landed, the implementation became more concrete:
- `RateLimitService` was added as the shared enforcement point
- the limiter became model-keyed and rolling-window based
- `RateLimitService` was made thread-safe so concurrent send-path use stays predictable
- `LLMResponseClient` began orchestrating preflight enforcement before adapter dispatch
- `RequestCapacityService` was explicitly kept separate to handle context and output window checks
- post-send usage recording was added so the limiter tracks actual request activity over time
- `LLMResponseClient` now requires the public `record_request_for_model` method and fails fast if it is missing

## What exists today
The current implementation includes:
- a model-keyed, thread-safe rolling-window `RateLimitService`
- token-per-minute checks with conservative fallback behavior
- request-per-minute checks when configured, with conservative fallback behavior
- optional waiting support for rate-limited requests when enabled by policy
- preflight orchestration in `LLMResponseClient`
- model-aware usage recording after successful request dispatch via the public `record_request_for_model` method
- separate capacity gating in `RequestCapacityService`
- integration through `RuntimeContext` and bootstrap wiring in `app.py`

This means the current system is functional and centralized, and it now covers the core enforcement path with safer limiter behavior, but it is still narrower than the larger policy vision described in the planning docs.

## Current implementation audit
Using the same review categories as the plan and checklist, the present status is:

- **Confirmed gaps**
  - provider-aware and tier-aware limit resolution is only partial
  - concurrency and thread-safety have been improved in the limiter, but broader cross-component guarantees have not been addressed explicitly
  - wait/retry semantics exist in a limited form, but the blocking policy surface remains incomplete
  - stronger observability and edge-case coverage remain incomplete

- **Design choice to confirm**
  - TPM fallback-to-1 behavior is now implemented conservatively, but still needs policy validation
  - TPM and RPM missing-value handling is intentionally conservative, but the exact fallback rules should be validated against the intended policy
  - optional waiting behavior should be confirmed as the desired default-versus-configured path

- **Product decision needed**
  - whether wait/retry should be expanded into a fuller schema-backed policy, and if so how blocking behavior should work
  - whether RPM should remain optional or become a more structured policy path
  - whether the current conservative fallback and omission behavior should be preserved, tightened, or made explicit in configuration

- **Intentional separation**
  - completion headroom is intentionally handled in capacity checks, not in rate limiting
  - capacity fit logic remains in `RequestCapacityService` rather than being folded into the limiter
  - adapter execution remains separate from enforcement so the send path stays easier to reason about and test

## What changed along the way
A few important shifts happened during the design and implementation process:

1. **Adapter responsibility was reduced**
   Rate limiting was moved out of the transport layer so the adapters remain focused on request execution.

2. **Capacity was separated from rate limiting**
   Context-window fit checks and completion-headroom logic were kept in `RequestCapacityService` instead of being folded into the limiter.

3. **The implementation became request-centric**
   `LLMResponseClient` now performs the preflight orchestration before calling the adapter, which makes the send path easier to reason about and test.

4. **Configuration resolution remained simple**
   The current code uses `ConfigService` and related accessors to determine the effective model limits instead of a full provider-tier policy engine. Provider-aware and tier-aware resolution exists only in partial form today.

5. **Recording stayed compatible while becoming model-aware**
   The client now requires the public `record_request_for_model` method for model-aware request recording.

## What remains to be done
The remaining work is mostly about policy depth, configurability, and verification:
- make wait behavior explicit through config accessors and, if needed, schema-backed policy support
- decide whether TPM enforcement should be expanded into a richer explicit policy layer
- decide whether RPM should remain optional or become a more structured policy
- validate the conservative TPM and RPM fallback rules and document the intended behavior
- resolve the current asymmetric handling of missing TPM and RPM values
- expand provider-aware or tier-aware limit resolution if required by future schemas
- add stronger tests around edge cases, blocking, fallback policy, rolling-window expiration, and stable behavior under timing variability
- improve observability around blocked requests, wait decisions, and effective limits
- determine whether concurrency and thread-safety constraints need any additional explicit handling across the broader send path

## Relationship to the docs
Use this file as the historical narrative.

Use `PLAN_RATE_LIMITING.md` as the implementation-aligned design document.

Use `CHECKLIST_RATELIMITING.md` as the work tracker for what is complete and what is still outstanding.

## Summary
The rate-limiting subsystem has moved from a broad architectural idea to a working OOP implementation:
- centralized enforcement exists
- the send path is gated before adapter dispatch
- capacity checks remain separate
- the implementation is functional, model-keyed, rolling-window based, thread-safe in the limiter, and includes optional waiting support, but it is not yet as policy-rich as the long-term plan

This roadmap exists to preserve that history while keeping future work grounded in what the code actually does today.
