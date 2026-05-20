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
- [ ] Confirmed gap: provider-aware and tier-aware resolution is correct for the initial implementation path. (Deferred — direct per-model lookup is sufficient for current shape.)
- [x] Conservative fallback handling is implemented for the current provider/model resolution path.
- [x] TPM fallback behavior: missing/0 → `None` (unlimited) + WARNING log. Removed the broken `default=1` fallback.
- [x] RPM missing-value behavior: missing/0 → `None` at accessor; rate-limit service treats `None` as fatal config error (ERROR log + `sys.exit(1)`). Removed the broken `default=0` that crashed `_validate_positive_limit`.
- [x] Reconciled asymmetric TPM/RPM missing-value behavior: TPM = soft (warning + unlimited), RPM = hard (error + exit). Both treat 0 and missing identically (coerced to None at the accessor).
- [x] Wait/retry behavior decision: deleted the unreachable wait-mode plumbing. If queue-and-wait is needed later, implement in a separate `RateLimitedScheduler` layer wrapping the gate (see PLAN_RATE_LIMITING.md).
- [x] Completion headroom remains separate from rate limiting — it's a capacity-preflight concern (`RequestCapacityService`), not a rate-limit concern.
- [x] Thread-safety: rolling-window state guarded by `RLock`.

## Milestone 1: Policy definition
- [x] Define rate limiting as a pre-send check rather than an adapter concern.
- [x] Define the limiter as model-aware (provider-aware/tier-aware deferred until needed).
- [x] Define token-per-minute enforcement as the primary mechanism.
- [x] Request-per-minute enforcement implemented as a mandatory config (RPM-missing exits).
- [ ] Define safety-factor application against provider ceilings. (Deferred — not needed in current scope.)
- [x] Define a single shared enforcement point for all LLM calls.
- [x] Make TPM enforcement soft-by-default (warning + unlimited if missing).
- [x] Make RPM enforcement mandatory (error + exit if missing).
- [x] Completion headroom remains a capacity concern, not a rate-limit concern.
- [x] Wait/queue policy deleted from the limiter — admission control only. Future wait/queue belongs in a `RateLimitedScheduler` layer wrapping the gate.
- [x] Server-mode behavior: deferred until server mode is built; gate is fail-fast.
- [x] Context windows and output windows are capacity guardrails, evaluated in `RequestCapacityService`.
- [x] Both preflights (`RequestCapacityService` and `RateLimitService`) delegate to the canonical `ConfigService.estimate_token_usage` estimator so they evaluate identical numbers.
- [x] Compaction is separate from rate limiting; compaction runs proactively *before* the LLM call so it acts before rate-limit preflight.

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
- [x] Add token estimation support — canonical estimator is `ConfigService.estimate_token_usage`; both preflights delegate.
- [x] Inject the limiter into `LLMResponseClient`.
- [x] Call the limiter before every adapter invocation via `check_request` (raises `RateLimitDeniedError` on denial).
- [x] Record usage after successful dispatch via `response.usage.total_tokens` (with shape-variant fallbacks and a preflight-estimate final fallback).
- [x] Cache `response.id → total_tokens` for chain-aware estimation on future `previous_response_id` calls.
- [x] Add thread-safety protections for the rolling-window state.
- [x] Add conservative fallback handling for missing or partial policy values (None at accessor, asymmetric soft/fatal at service).
- [x] Normalize accounting keys (strip provider prefix, lowercase).
- [x] Surface structured denial diagnostics: `RateLimitDeniedError` with `reason`, `current`, `limit`, `retry_after_seconds`.
- [x] REPL surfaces denials to stdout with the loop continuing.
- [x] TUI surfaces denials with a yellow `rate limited (idle)` indicator + red transcript line via `failure_kind="rate_limited"`.
- [x] Deleted wait-mode plumbing (`allow_wait`, `wait_timeout_seconds`, polling loop, `_compute_wait_deadline`, `_wait_timed_out`, the three config getattr probes that read non-existent fields).
- [x] Collapsed `_get_model_rate_limit` four-name helper to direct field reads; removed unreachable per-model fallback machinery (`_get_rate_limit_fallback`, `_resolve_model_name`).

## Milestone 6: Verification
- [x] Tests for preflight approval and rejection (with structured exception assertions).
- [x] Tests for `RateLimitDeniedError` structure (reason, model, current, limit, retry_after_seconds).
- [x] Tests for rolling-window behavior.
- [x] Tests for unconfigured TPM (unlimited + warning log).
- [x] Tests for unconfigured RPM (error log + SystemExit(1)).
- [x] Tests for accounting-key normalization (provider-prefixed and bare model names share budget; case-insensitive).
- [x] Tests for chain-aware estimation (cached baseline, cache miss, LRU eviction, None inputs ignored).
- [x] Tests for actual-usage recording (total_tokens, input+output shape, fallback to preflight estimate).
- [x] Tests for estimator consistency between `RequestCapacityService` and `RateLimitService`.
- [x] Tests for thread safety and concurrent rate-limit updates.
- [x] Tests for fallback handling and policy validation.
- [x] Behavior-focused tests for the response client and limiter integration.
- [x] REPL test: rate-limit denial prints to stdout and the loop continues.
- [x] TUI tests: rate-limit denial produces `rate limited (idle)` status via the existing event path.
- [x] All tests use only the public interface (no private (`_`-prefixed) attribute or method access).

## Notes
- The limiter is a pure admission-control gate; wait/queue semantics belong above it (future `RateLimitedScheduler`).
- Token estimation is canonical via `ConfigService.estimate_token_usage` — no duplication across layers.
- Each denial logs the effective budget and the reason; `RateLimitDeniedError.__str__` is user-facing.
- The public service interface is stable so provider support can expand later without refactoring call sites.
