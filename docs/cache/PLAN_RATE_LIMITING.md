# PLAN_RATE_LIMITING

## Goal
Define how `monitor_oop` should rate limit outbound LLM requests in a provider-aware way that works for the current OpenAI path and the near-future Anthropic path implemented through a LiteLLM-backed Responses API adapter.

The rate limiter should be centralized, deterministic, and adapter-agnostic. The request path should ask for permission before each LLM call, then record usage only after the request is actually dispatched. The same limiter must work for normal chat calls, tool-call follow-ups, summarization calls, retries, and future provider integrations.

## Current Direction
The intended design is a shared runtime service that enforces token-based limits across providers:
- `RateLimitService` owns policy evaluation and rolling-window accounting.
- `TokenEstimator` estimates request cost before dispatch.
- `ConfigService` provides model, provider, and configured budget information.
- `LLMResponseClient` calls the limiter before invoking the adapter.
- Provider adapters remain transport-only and do not embed rate limiting logic.
- The future Anthropic adapter should reuse the same limiter through the same service boundary.

The first implementation slice already includes `RequestCapacityService`, `RateLimitService`, and `LLMResponseClient` preflight orchestration. Capacity checks happen before rate limiting, and adapter dispatch happens only after both checks pass.

The schema-backed runtime config source is `RuntimeConfig` via `config_loader`, with the current greenfield rate-limit and config schema living in `src/monitor_oop/model_config_v2.json`.

The limiter currently resolves TPM from the model config, with RPM kept minimal and optional.

The limiter should primarily enforce token-per-minute behavior, with optional request-per-minute checks if needed later.

Note: `context_window_mapping` and `output_window_mapping` are capacity guardrails, not the rate limit itself. Context windows determine whether the request fits, output windows determine completion headroom, and TPM/RPM enforcement remains the time-based usage budget. Compaction is a separate capacity-management concern driven by context-window pressure; when a request needs resizing, compaction should occur before rate-limit preflight. The current code path preserves this separation by checking capacity first, then applying rate limiting, and only then dispatching to the adapter.

## Guiding Principles
- Centralize all LLM send-path rate limiting in one service.
- Keep provider-specific knowledge in configuration, not in adapter code.
- Estimate tokens before each request using the full payload, not just the latest user message.
- Record usage only after the request is approved and sent.
- Make the policy easy to test in isolation.
- Keep the design compatible with LiteLLM-based provider adapters.
- Prefer fail-fast or wait-then-proceed behavior depending on configuration, but keep the choice consistent and explicit.

## Proposed Runtime Flow
1. Build the request payload.
2. Estimate the token cost for the full payload.
3. Determine provider and model from runtime config.
4. Ask `RateLimitService` whether the request may proceed.
5. If the request is blocked, either wait until permitted or return a clear error, depending on policy.
6. Dispatch the request through the adapter.
7. Record the actual or estimated usage after dispatch.
8. Repeat the same flow for any follow-up tool calls or summarization requests.

## Policy Model
The initial policy should be token-based and provider-aware:
- track a rolling window of token usage per provider/model
- apply a safety factor to stay below provider ceilings
- optionally reserve completion headroom
- optionally track request counts alongside token counts
- optionally distinguish between primary requests and follow-up requests if later needed for observability

Suggested precedence for effective limits:
1. exact model limit
2. provider-level limit
3. global default limit
4. disabled rate limiting when no usable limit exists

### Recommended Initial Policies
- Enforce TPM by default.
- Keep RPM optional and off by default.
- Reserve modest completion headroom with a configurable factor and floor.
- Prefer wait-then-fail behavior for interactive CLI/TUI usage.
- Prefer fail-fast or short-wait behavior for server mode.

## Config Surface
The intended config surface should stay small but extensible:
- `rate_limiting.enabled`
- `rate_limiting.window_seconds`
- `rate_limiting.safety_factor`
- `rate_limiting.default_tpm`
- provider-specific TPM ceilings, keyed by provider name
- optional model-specific TPM ceilings, keyed by model name
- optional completion reserve settings for headroom
- optional wait-vs-fail policy selection

The config should be loaded through `RuntimeConfig` and `config_loader`, backed by `src/monitor_oop/model_config_v2.json`, rather than embedded in adapters or free functions.

## Canonical Future Loader Schema
The recommended canonical schema for the future loader is an explicit model-to-provider-to-tier resolution format using `provider_table/tier_key`. See `docs/cache/PLAN_MODEL_CONFIG_V2.md` for the schema contract; `RateLimitService` depends on that contract to resolve effective limits deterministically.

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
The limiter should treat each send as a reservation and then a commit:
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
- a completion reserve when appropriate

## Rolling Window Strategy
Use a rolling-window structure keyed by provider and model:
- store timestamped token events
- purge events older than `window_seconds`
- compute current usage on demand
- avoid mutable module globals

For a single-process desktop or CLI app, an in-memory deque-based implementation is sufficient. If multi-process support is needed later, the service can be backed by Redis or another shared store without changing the public API.

## Recommendations for OOP Integration
For `monitor_oop`, the most maintainable plan is:
- add a dedicated `rate_limit_service.py` under `core/infrastructure/`
- inject it into `LLMResponseClient`
- have `LLMResponseClient.create_response(...)` call it before every adapter invocation
- keep provider/model resolution in `ConfigService`
- keep token estimation in a shared utility or service
- wire the same limiter into future Anthropic/LiteLLM request paths

## Verification Focus
Any implementation should be verified for:
- preflight rate checks before every LLM send
- correct provider/model resolution
- consistent token estimates across normal, follow-up, summary, and retry paths
- safety-factor application
- rolling-window expiration behavior
- correct commit behavior after successful dispatch
- no duplicate enforcement inside adapters
- compatibility with a future Anthropic LiteLLM adapter

## Notes
- Prefer a single shared enforcement point over scattered checks.
- Keep the first version deterministic and well instrumented.
- If waiting is supported, make the timeout and behavior explicit.
- Log the effective provider/model limit and the reason a request was delayed or blocked.
- The design should remain easy to expand as more providers are added.
