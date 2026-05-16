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
- `LLMResponseClient` began calling the limiter before adapter dispatch
- `RequestCapacityService` stayed separate to handle context and output window checks
- post-send usage recording was added so the limiter tracks actual request activity over time

## What exists today
The current implementation includes:
- a rolling-window `RateLimitService`
- token-per-minute checks
- request-per-minute checks when configured
- preflight enforcement in `LLMResponseClient`
- usage recording after successful request dispatch
- separate capacity gating in `RequestCapacityService`
- integration through `RuntimeContext` and bootstrap wiring in `app.py`

This means the current system is functional and centralized, but still narrower than the larger policy vision described in the planning docs.

## Current implementation audit
Using the same review categories as the plan and checklist, the present status is:

- **Confirmed gaps**
  - provider-aware and tier-aware limit resolution is only partial
  - concurrency and thread-safety have not been addressed explicitly
  - wait/retry semantics are not implemented
  - stronger observability and edge-case coverage remain incomplete

- **Design choice to confirm**
  - TPM fallback-to-1 behavior is still a choice to confirm
  - TPM and RPM missing-value handling is asymmetric and should be validated against the intended policy

- **Product decision needed**
  - whether wait/retry should be added at all, and if so how blocking behavior should work
  - whether RPM should remain optional or become a more structured policy path
  - whether the current fallback and omission behavior should be preserved or tightened

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
   `LLMResponseClient` now performs the preflight checks before calling the adapter, which makes the send path easier to reason about and test.

4. **Configuration resolution remained simple**
   The current code uses `ConfigService` and related accessors to determine the effective model limits instead of a full provider-tier policy engine. Provider-aware and tier-aware resolution exists only in partial form today.

## What remains to be done
The remaining work is mostly about policy depth, configurability, and verification:
- decide whether TPM enforcement should be expanded into a richer explicit policy layer
- decide whether RPM should remain optional or become more structured
- confirm whether TPM fallback-to-1 should remain the default behavior
- resolve the current asymmetric handling of missing TPM and RPM values
- add wait/retry semantics if the product needs them
- define whether completion reserve belongs in rate limiting or only in capacity management
- expand provider-aware or tier-aware limit resolution if required by future schemas
- add stronger tests around edge cases, blocking, and rolling-window expiration
- improve observability around blocked requests and effective limits
- determine whether concurrency and thread-safety constraints need explicit handling

## Relationship to the docs
Use this file as the historical narrative.

Use `PLAN_RATE_LIMITING.md` as the implementation-aligned design document.

Use `CHECKLIST_RATELIMITING.md` as the work tracker for what is complete and what is still outstanding.

## Summary
The rate-limiting subsystem has moved from a broad architectural idea to a working OOP implementation:
- centralized enforcement exists
- the send path is gated before adapter dispatch
- capacity checks remain separate
- the implementation is functional, but not yet as policy-rich as the long-term plan

This roadmap exists to preserve that history while keeping future work grounded in what the code actually does today.
