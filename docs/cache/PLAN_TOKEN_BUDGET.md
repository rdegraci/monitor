# PLAN_TOKEN_BUDGET

## Goal
Reduce `context_length_exceeded` failures during Responses API follow-up calls by budgeting against the full effective request instead of budgeting only visible tool-output text.

## Problem statement
Current follow-up budgeting in `src/monitor/core/llm_responses_adapter.py` trims `function_call_output` payloads based mainly on visible `input` token estimates. That is helpful but incomplete because the provider also counts additional request components, including:

- hidden prior-chain context referenced by `previous_response_id`
- tool schema payload when `tools` is sent on the follow-up
- structured wrapper overhead for `function_call_output` items
- top-level request envelope overhead

The source code already documents that local token counting underestimates true Responses API request size for these reasons.

## Proposed direction
Introduce full-request budgeting for follow-up requests.

Instead of asking only whether `input` fits, compute a reduced payload budget after reserving space for:

1. hidden chain overhead
2. tool schema overhead
3. structured payload overhead
4. top-level request overhead
5. a global safety margin

Then trim tool outputs to fit within the remaining payload budget.

## Integration strategy
### Phase 1: full-request reserve calculator
Add a helper that:
- classifies request shape
- computes usable input window
- computes named reserve buckets
- returns remaining payload budget for `input`

This phase should reuse the existing trimming mechanics (item iteration,
truncation markers) but own the budget number. Critically, the calculator must
**subsume** the current `0.85` safety ratio and the `0.8` trim target inside
`token_budgeter(...)` — wrapping the calculator ahead of a path that re-applies
those constants would compound the discounts and over-trim. Retire the old
constants as the reserve model takes over.

Expose the budget computation as a **pure function** (`classify → usable window
→ reserves → input_payload_budget`) so it is unit-testable without issuing any
network calls. This is the primary validation seam.

Phase boundary: Phase 1 owns the calculator shape, the config-driven tunable
reserves, the usable-window math, the two gating-site reconciliation, and the
logging/admission contract. Exact structural measurement of the tool catalog
and `function_call_output` shells is intentionally deferred to Phase 2.

Reconcile both gating sites. `INPUT_WINDOW_SAFETY_RATIO` is applied in **two**
places in `llm_responses_adapter.py`: the follow-up trimming block (~line 643)
and a separate input-size gate (~line 1644). Retiring the constant means routing
**both** through `FOLLOWUP_BASE_SAFETY_RATIO`; leaving one behind would let the
two sites diverge. Source the per-depth reserve from the existing `iteration`
counter (the function-call loop variable already in scope at the follow-up site).

### Phase 2: structure-aware payload estimation
Improve token estimation so that follow-up budgeting counts more than just `content` / `output` text. For `function_call_output` items, include shell overhead such as:
- `type`
- `call_id`
- serialized object structure

Implement this with a **dedicated structural-counting helper** that token-counts
`json.dumps(obj)`, used only by the reserve calculator. The canonical
`count_message_tokens(...)` counts text only (by design) and must not be changed;
extending it would break callers that rely on its text-only contract. Use the
new helper to measure the tool catalog and the `function_call_output` shells
exactly — these are measured reserves, not estimates. See
`SPEC_TOKEN_BUDGET.md` → "Counting the measured reserves".

This phase is where any Phase 1 placeholder/provisional handling for the
measured buckets is replaced by exact structural counts. The hidden-chain
reserve remains the only estimated bucket.

### Phase 3: fallback policy
If the full-request budget leaves too little room for normal tool follow-up, route to a safer fallback mode, such as:
- no-tools summarization follow-up
- fresh request rebase with compact summary
- minimal answer mode with trimmed tool-result stubs

Baseline requirement: route the `fallback` admission outcome into the adapter's
existing summarization/rebase path. Fresh-chain rebase and minimal-answer
variants are optional extensions within this phase, not prerequisites for
landing the first fallback behavior.

### Phase 4: empirical tuning
Once Phases 1–3 are in production, calibrate the tunable knobs against observed
behavior rather than the seed constants:
- recalibrate the hidden-chain reserve per model family (a `_BY_MODEL` override
  layered over `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS`, mirroring the existing
  `MODEL_TOKEN_RATE_PER_MTOK` pattern)
- tune the per-depth reserve and its cap ratio from real chain-depth data
- close the loop using the structured preflight logs and actual provider
  `context_length_exceeded` errors

This phase changes config values and tuning tables only — no new admission-control
mechanism. See `ROADMAP_TOKEN_BUDGET.md` → "Phase 4".

## Request classes
Use request-shape-specific budgeting rules:

- `fresh_request`
- `chained_user_followup`
- `tool_result_followup`
- `summarization_followup`

Tool-result follow-ups should receive the strictest reserve policy because they have the highest context-overrun risk.

## Reserve buckets
Two of these are measured exactly, not estimated — see the measured/estimated
split in `SPEC_TOKEN_BUDGET.md`. Only the hidden chain reserve carries a tunable
margin in the end-state policy. During Phase 1, the calculator shape and config
surface land first; exact structural measurement for the measured buckets lands
in Phase 2.

### Hidden chain reserve (estimated)
Reserve for server-side context implied by `previous_response_id`. The only
genuinely-hidden bucket; carries the tunable uncertainty margin.

### Tool schema reserve (measured)
Count the serialized `tools` + `tool_choice` actually being sent. Do not estimate.

### Structured payload reserve (measured)
Count the full serialized `function_call_output` item shells, not just raw
`output` text. The adapter already builds these shells.

### Top-level reserve
Small flat reserve (~256 tokens) for request envelope and optional parameters.

### Global safety margin
A single `base_safety_ratio` applied to the model input window. This **replaces**
the existing `INPUT_WINDOW_SAFETY_RATIO = 0.85` and the `0.8` trim target inside
`token_budgeter(...)`; it must not stack on top of them.

## Starting policy guidance
Treat the model input window as `W` and derive a smaller usable window, then subtract named reserves before trimming payload text.

Suggested order of operations:
1. determine request class
2. compute usable window from `W`
3. estimate all named reserves
4. compute `input_payload_budget`
5. trim or summarize `input` to fit that budget
6. fallback instead of sending if the budget is too small

## Logging expectations
For every follow-up preflight, log:
- request class
- model input window
- usable window
- hidden chain reserve
- tool schema reserve
- structured payload reserve
- top-level reserve
- computed payload budget
- original input estimate
- final input estimate after trimming
- send vs fallback decision

## Risks
- reserve policy may be too strict initially and over-trim tool output
- reserve policy may still be too optimistic for some models or long chains
- fallback behavior must preserve enough semantic information for good answers

## Success criteria
- materially fewer `context_length_exceeded` failures during tool follow-ups
- clearer observability for why a request was trimmed or rejected
- safer handling of long chained Responses API sessions

## Notes
This plan intentionally favors incremental integration. The first implementation
should introduce the full-request reserve calculator as the single source of the
follow-up budget, retiring the existing `0.85` safety ratio and `0.8` trim target
rather than layering on top of them. The calculator's pure budget function is the
unit-test target; the surrounding adapter flow is exercised via the existing
trimming mechanics.

The `summarization_followup` request class is not new machinery — it names the
shape produced by the adapter's existing summarization/rebase fallback path. The
budgeting policy classifies and budgets that path; the `fallback` outcome routes
into it. See `SPEC_TOKEN_BUDGET.md`.
