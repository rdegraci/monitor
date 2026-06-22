# ROADMAP_TOKEN_BUDGET

## Objective
Roll out full-request budgeting for Responses API follow-up calls in phases so context-window safety improves without destabilizing existing tool-call behavior.

## Phase 1: reserve-aware preflight
### Deliverables
- request-shape classification
- usable-window calculation (subsumes today's `0.85`/`0.8` constants; does not stack)
- named reserve buckets with seed starting constants and a pure budget-calculator seam
- pure, network-free budget function as the unit-test seam
- reduced payload budget for follow-up `input`
- structured logging for reserve accounting

Phase boundary: Phase 1 lands the calculator shape and tunable reserve policy.
Exact structural measurement for tool-schema and `function_call_output` shell
overhead is deferred to Phase 2.

### Expected impact
- immediate improvement in follow-up safety
- better diagnostics for oversized requests

## Phase 2: structure-aware estimation
### Deliverables
- exact measurement of `function_call_output` shell overhead (counted, not estimated)
- exact measurement of serialized tool-schema size
- hidden-chain reserve left as the only unmeasurable / estimated bucket

### Expected impact
- lower mismatch between local estimates and provider-side reality
- fewer false-safe admissions

## Phase 3: fallback strategies
### Deliverables
- route `fallback` into the existing no-tools summarization/rebase path
- optional fresh-chain rebase strategy for risky long chains
- optional policy for minimal stubs when tool output must be heavily reduced

### Expected impact
- fewer hard failures when full tool follow-ups are too large
- more graceful degradation under budget pressure

## Phase 4: empirical tuning
### Deliverables
- reserve calibration per model family
- chain-depth tuning for hidden-context reserves
- telemetry review loop using logged preflight decisions and provider errors

### Expected impact
- better balance between safety and retained tool detail
- model-specific optimization over time

## Decision points
### After Phase 1
Evaluate whether the reserve-aware preflight alone materially reduces `context_length_exceeded` errors.

### After Phase 2
Evaluate whether structure-aware estimation reduces the need for overly conservative safety margins.

### After Phase 3
Evaluate whether fallback behavior preserves answer quality when standard tool-result follow-ups are rejected.

## Success measures
- lower incidence of follow-up request 400 context-length failures
- predictable trimming behavior with auditable logs
- reduced dependence on ad hoc safety-ratio tuning alone
