# TUNING_TOKEN_BUDGET

Operational guide for tuning the Responses API follow-up budget policy after
Phases 1-3 are in place.

This is not a code-change plan. It is the step-by-step procedure for adjusting
the existing config knobs in `src/monitor/config.yaml.example` and validating
their effect on real workloads.

## Goal

Reduce follow-up request failures such as `context_length_exceeded` while
preserving as much tool-result detail as possible.

The tuning problem is a tradeoff:

- too loose -> provider rejects chained/tool-result follow-ups
- too strict -> the adapter trims aggressively or falls back to summarization
  too early

## Knobs You Can Tune

These are the current knobs exposed in config:

- `FOLLOWUP_BASE_SAFETY_RATIO`
- `FOLLOWUP_TOPLEVEL_RESERVE_TOKENS`
- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS`
- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`

Practical priority:

1. `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS`
2. `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
3. `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`
4. `FOLLOWUP_BASE_SAFETY_RATIO`
5. `FOLLOWUP_TOPLEVEL_RESERVE_TOKENS`

In most cases, the hidden-chain knobs matter more than the top-level reserve.

## Runtime Signals

The adapter now emits a structured preflight log line for every tool-result
follow-up:

`Follow-up budget preflight: class=... input_window=... usable_window=... hidden_chain_reserve=... tool_schema_reserve=... structured_payload_reserve=... top_level_reserve=... payload_budget=... original_input_estimate=... final_input_estimate=... decision=...`

It also emits these important decision logs:

- `Routing tool-result follow-up into summarization/rebase fallback ...`
- `Skipping follow-up responses.create: estimated tokens (...) exceed rate-limiter safety threshold`
- `Skipping summarization follow-up: estimated tokens (...) exceed rate-limiter safety threshold`

Use these together with any actual provider `context_length_exceeded` errors.

## What The Decisions Mean

- `decision=send`
  - request fit without trimming
- `decision=send_trimmed`
  - request only fit after tool-result trimming
- `decision=fallback`
  - normal tool-result follow-up was rejected by the budget policy and routed
    into summarization/rebase
- `decision=unknown_budget`
  - no valid `MODEL_INPUT_WINDOW` / `MODEL_CONTEXT_WINDOW` was available, so
    strict admission control did not run

`unknown_budget` is a configuration problem first, not a tuning problem.

## Before You Tune

1. Pick one or two real workloads that previously caused pain:
   - long tool chains
   - large tool outputs
   - repeated `previous_response_id` follow-ups
2. Keep those workloads stable while tuning.
3. Change one knob at a time.
4. Do not tune against a single run. Look for a repeated pattern.

## Step-By-Step Procedure

### 1. Capture a baseline

Run the same representative workload with the current defaults and collect:

- whether you hit `context_length_exceeded`
- how often follow-ups are:
  - `send`
  - `send_trimmed`
  - `fallback`
- whether final answers are still useful after trimming/fallback

Baseline questions:

- Are provider errors still happening?
- Are there too many fallbacks?
- Are there too many trims even when provider errors are gone?

### 2. Identify the failure mode

Use the logs to sort the problem into one of these buckets.

#### A. Provider still rejects requests

Symptoms:

- actual `context_length_exceeded`
- preflight often says `send` or `send_trimmed`, but the provider still fails

Interpretation:

- the budget is too optimistic

#### B. Too many `fallback` decisions

Symptoms:

- no provider errors
- many requests route directly into summarization/rebase
- answers lose too much tool detail

Interpretation:

- the budget is too conservative

#### C. Too many `send_trimmed` decisions

Symptoms:

- requests mostly fit only after trimming
- provider errors may be gone, but answer quality suffers

Interpretation:

- the budget may be slightly too conservative, or the chain-depth reserve may
  be growing too fast

#### D. `unknown_budget`

Symptoms:

- `decision=unknown_budget`

Interpretation:

- fix `MODEL_INPUT_WINDOW` / `MODEL_CONTEXT_WINDOW` first

### 3. Tune the hidden-chain reserve first

This is the primary tuning surface.

Start with `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS`.

#### If requests are still overrunning

Increase:

- `tool_result_followup`
- optionally `chained_user_followup` if smaller chained turns also fail

Recommended pattern:

- increase in moderate steps, e.g. `+500` or `+1000`
- rerun the same workload

Do not change the safety ratio first unless the failures are broad across all
follow-up classes.

#### If you see too many fallbacks

Decrease:

- `tool_result_followup`

Recommended pattern:

- reduce in moderate steps, e.g. `-500`
- stop once provider failures begin to reappear

### 4. Tune depth growth

Only touch this after the base per-class reserve is roughly right.

Relevant knobs:

- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`

Use these when the problem appears mainly on deeper chains.

#### If deep chains still fail but shallow ones are fine

Increase:

- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
- or, if it is already large, raise `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`

#### If deep chains fallback too early

Decrease:

- `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
- or lower `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`

Heuristic:

- if shallow chains are healthy and only deep chains are bad, prefer depth
  tuning over changing `FOLLOWUP_BASE_SAFETY_RATIO`

### 5. Tune the safety ratio only when the problem is broad

`FOLLOWUP_BASE_SAFETY_RATIO` scales the whole usable window.

Use it when:

- multiple request classes look systematically too optimistic
- multiple request classes look systematically too conservative

#### If the whole policy is too optimistic

Lower `FOLLOWUP_BASE_SAFETY_RATIO`

Example direction:

- `0.85 -> 0.82`
- `0.82 -> 0.80`

#### If the whole policy is too conservative

Raise `FOLLOWUP_BASE_SAFETY_RATIO`

Example direction:

- `0.85 -> 0.87`
- `0.87 -> 0.90`

Do this carefully. It affects every follow-up class, not just the risky ones.

### 6. Leave the top-level reserve alone unless you have evidence

`FOLLOWUP_TOPLEVEL_RESERVE_TOKENS` is usually not the main lever.

Adjust it only if:

- preflight logs show a persistent small miss that does not correlate with
  hidden-chain depth
- you have reason to believe the request envelope overhead is systematically
  under- or over-reserved

In most workloads, hidden-chain tuning is the real control surface.

### 7. Re-run the same workload after every change

After each change, compare to baseline:

- provider failures fewer / same / more?
- `send_trimmed` fewer / same / more?
- `fallback` fewer / same / more?
- final answers better / same / worse?

If one change improves safety but destroys answer quality, back it out and use
the more targeted hidden-chain/depth knobs instead of broad safety-ratio changes.

## Suggested Tuning Order

If you want a strict sequence, use this:

1. fix any `unknown_budget` cases
2. tune `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS.tool_result_followup`
3. tune `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
4. tune `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`
5. tune `FOLLOWUP_BASE_SAFETY_RATIO`
6. touch `FOLLOWUP_TOPLEVEL_RESERVE_TOKENS` only if still justified

## Example Decision Guide

### Case 1: real provider overruns on long tool chains

Observed:

- `decision=send`
- later `context_length_exceeded`

Action:

- increase `tool_result_followup`
- if failures happen mostly on deeper chains, also increase
  `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`

### Case 2: no provider errors, but many summarization fallbacks

Observed:

- lots of `decision=fallback`
- answers are too lossy

Action:

- decrease `tool_result_followup`
- if this mostly affects deeper chains, reduce per-depth growth instead of
  changing the global safety ratio

### Case 3: almost everything is `send_trimmed`

Observed:

- little hard failure
- many trims
- answer quality degraded

Action:

- reduce hidden-chain reserve slightly
- or increase `FOLLOWUP_BASE_SAFETY_RATIO` slightly if the conservatism is
  broad across classes

## When To Stop

Stop tuning when all of these are true:

- `context_length_exceeded` is rare or gone on representative workloads
- `fallback` is reserved for genuinely large/risky cases
- `send_trimmed` happens sometimes but does not dominate
- answer quality remains acceptable

## Notes

- Tune in config first. Do not start with code changes.
- If one model family needs materially different behavior from another, that is
  the signal for a future per-model override layer, not for encoding
  model-specific behavior into manual ad hoc tweaks.
- Phase 4 is successful when you can explain the current numbers from observed
  logs and workloads, not when the numbers merely “look reasonable.”
