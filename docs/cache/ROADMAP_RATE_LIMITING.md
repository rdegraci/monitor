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
- A model-keyed, thread-safe rolling-window `RateLimitService` used as a *pure admission-control gate*.
- Single-shot `check_request(model, estimated_tokens)` that returns on success and raises `RateLimitDeniedError` on denial. The exception carries `reason` (`"tpm"`/`"rpm"`), `model`, `current`, `limit`, and `retry_after_seconds` computed from the oldest in-window event timestamp.
- Normalized accounting keys (strip `provider/` prefix, lowercase) so `"openai/gpt-4o"` and `"gpt-4o"` share a budget.
- Asymmetric missing-value handling: missing TPM → WARNING log + unlimited; missing RPM → ERROR log + `sys.exit(1)`. Explicit `0` is coerced to `None` at the accessor for both.
- Chain-aware token estimation: a bounded LRU cache (`response.id → total_tokens`) populated from `response.usage.total_tokens` on every successful request. When a future request chains via `previous_response_id`, the cached value is added as a baseline so the preflight reflects server-side context.
- Post-send recording uses provider-reported `response.usage.total_tokens` (with shape-variant fallbacks).
- Canonical estimator shared between `RequestCapacityService` and `RateLimitService` via `ConfigService.estimate_token_usage` — both preflight gates evaluate identical numbers.
- REPL and TUI surface denials to the user (REPL: `[rate limit] <message>` to stdout, loop continues; TUI: yellow `"rate limited (idle)"` status + red transcript line via `failure_kind="rate_limited"`).
- Integration through `RuntimeContext` and bootstrap wiring in `app.py`.
- Deleted: the entire wait-mode plumbing (`allow_wait`, `wait_timeout_seconds`, `wait_policy`, polling loop, `_compute_wait_deadline`, `_wait_timed_out`, three config getattr probes) — it was unreachable in production because the config fields it probed didn't exist.

This means the system is functional, structured, and centralized. The remaining policy vision (provider/tier-aware resolution, wait/queue semantics) is intentionally deferred to a future `RateLimitedScheduler` layer when needed by an agent-orchestrator deployment.

## Current implementation audit
Using the same review categories as the plan and checklist, the present status is:

- **Confirmed gaps**
  - provider-aware and tier-aware limit resolution is only partial
  - concurrency and thread-safety have been improved in the limiter, but broader cross-component guarantees have not been addressed explicitly
  - wait/retry semantics exist in a limited form, but the blocking policy surface remains incomplete
  - stronger observability and edge-case coverage remain incomplete
  - brittle private-helper tests were removed, and the remaining compaction tests focus on durable public behavior
  - compaction now uses context-window pressure with explicit output headroom and an estimator-backed token count, but the turn-budget fallback path still needs clearer policy framing
  - summarization versus compaction naming and roles may need to be clarified if they are intended to be distinct

- **Design choice to confirm**
  - TPM fallback-to-1 behavior is now implemented conservatively, but still needs policy validation
  - TPM and RPM missing-value handling is intentionally conservative, but the exact fallback rules should be validated against the intended policy
  - optional waiting behavior should be confirmed as the desired default-versus-configured path
  - compaction estimator behavior, output headroom, and turn-budget fallback should be confirmed as the intended policy split

- **Product decision needed**
  - whether wait/retry should be expanded into a fuller schema-backed policy, and if so how blocking behavior should work
  - whether RPM should remain optional or become a more structured policy path
  - whether the current conservative fallback and omission behavior should be preserved, tightened, or made explicit in configuration
  - whether compaction should remain driven by context pressure, explicit output headroom, estimator-backed token counts, and a turn-budget fallback

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
The rate-limit subsystem has no known correctness bugs and no urgent hygiene gaps. Future work is conditional on deployment shape:
- Build a `RateLimitedScheduler` layer wrapping the gate if/when agent-under-orchestrator mode needs queue-and-wait semantics. The scheduler computes "next admission moment" from the deque state and sleeps once until then — no polling.
- Expand provider-aware / tier-aware limit resolution if a richer config schema lands.
- Close the cold-cache gap on chained requests (the first `previous_response_id` after a process restart has no cached baseline). Mitigation today: post-call recording reconciles for the next turn. Full fix would persist the cache across processes — overkill for the current single-process shape.
- Improve observability around denied requests if production telemetry requires it.

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
