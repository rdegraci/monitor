# SPEC_TOKEN_BUDGET

## Purpose
Define a full-request budgeting policy for Responses API follow-up calls so admission control accounts for the effective entire request, not only visible tool-output text.

## Scope
This spec applies to follow-up `responses.create` requests, especially tool-result follow-ups using:
- `previous_response_id`
- `function_call_output` items
- optional `tools`

## Definitions
### Model input window
The configured request budget source, typically:
1. `MODEL_INPUT_WINDOW`, else
2. `MODEL_CONTEXT_WINDOW`

### Usable window
A reduced request budget derived from the model input window after applying a global safety reduction.

### Full-request reserves
Named deductions from the usable window before allocating budget to request `input`.

Reserves fall into two categories, and the distinction is load-bearing:

- **Measured** — components that are fully known at request time and must be
  counted exactly, not approximated with a margin: the serialized tool catalog
  (`tools` + `tool_choice`) and the `function_call_output` item shells. The
  adapter already serializes these (the candidate-item dicts and the tool
  payload), so reserving an "uncertainty margin" for them only bakes in
  avoidable over-trimming.
- **Estimated** — the genuinely hidden component that cannot be measured
  locally: server-side context referenced by `previous_response_id`. This is
  the only bucket that should carry a tunable uncertainty margin.

Design rule: measure what is measurable, reserve only for what is hidden.
Prefer collapsing the tunable surface to the single hidden-chain reserve rather
than carrying four independently-tuned knobs.

This is the end-state contract. The phased implementation may land the reserve
calculator and tunable policy surface first, then teach it exact structural
counts for the measured buckets in Phase 2.

## Request classes
### `fresh_request`
No `previous_response_id`; first request in a chain.

### `chained_user_followup`
Has `previous_response_id`; input is a small user follow-up.

### `tool_result_followup`
Has `previous_response_id`; input is a list of `function_call_output` items.

### `summarization_followup`
Has `previous_response_id`; input is a compact summary-oriented payload and should usually omit tools.

This class is **not new machinery** — it names the request shape produced by the
adapter's existing summarization/rebase fallback path (the
`build_function_call_output_item` / summarization-follow-up flow). The budgeting
policy should classify and budget that existing path, not reimplement it. The
`fallback` admission outcome routes into that same code.

## Budgeting model
Let `W` be the configured model input window.

### Step 1: usable window
Compute:
- `usable_window = floor(W * base_safety_ratio)`

The base safety ratio should be conservative because local estimation undercounts provider-side request cost.

This ratio **subsumes** the existing ad-hoc margins, it does not stack on top of
them. The current adapter already applies `INPUT_WINDOW_SAFETY_RATIO = 0.85` and
a separate `0.8` trim target inside `token_budgeter(...)`. The reserve model
must replace those, not run ahead of a path that re-applies them — otherwise the
discounts compound and the request is over-trimmed. When this policy lands, the
old `0.85`/`0.8` constants are retired in favor of `base_safety_ratio` plus the
named reserves.

### Step 2: reserve buckets
Deduct the following reserves from `usable_window`.

#### Hidden chain reserve (estimated)
Applies when `previous_response_id` is present.

Purpose:
- account for invisible server-side context
- absorb chain-related uncertainty

This is the **only** genuinely-estimated reserve — the server-side context
cannot be measured locally. It should be highest for `tool_result_followup` and
may increase with chain depth. It is therefore the bucket that carries the
tunable uncertainty margin (see Starting constants).

#### Tool schema reserve (measured)
Applies when `tools` are included in the request.

Purpose:
- account for the serialized tool catalog and `tool_choice`

This is a **measured** quantity: serialize the tool catalog actually being sent
and count it. Do not substitute an estimate plus margin — the exact value is
available at request time.

#### Structured payload reserve (measured)
Applies primarily to `function_call_output` items.

Purpose:
- account for object shell overhead such as:
  - `type`
  - `call_id`
  - serialized dict structure

This is a **measured** quantity: count the full serialized item shell, not just
the raw `output` text. The adapter already builds these shells, so the exact
overhead is available — do not infer it from output text size or a flat margin.

#### Top-level reserve
Applies to all follow-up requests.

Purpose:
- reserve room for request envelope fields and optional parameters

## Payload budget
After reserves are computed:
- `input_payload_budget = usable_window - hidden_chain_reserve - tool_schema_reserve - structured_payload_reserve - top_level_reserve`

If `input_payload_budget <= 0`, the normal follow-up request is not safe to send.

## Starting constants
These are seed values to make Phase 1 actionable, not tuned results. Phase 4
calibrates them against logged preflight decisions and real provider errors.

- `base_safety_ratio = 0.85` — carried over from today's `INPUT_WINDOW_SAFETY_RATIO`
  (config key `FOLLOWUP_BASE_SAFETY_RATIO`).
- Tool schema reserve — measured; no constant.
- Structured payload reserve — measured; no constant.
- Top-level reserve — `~256` tokens flat for the request envelope
  (config key `FOLLOWUP_TOPLEVEL_RESERVE_TOKENS`).
- Hidden chain reserve (the only tunable margin; config key
  `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS`):
  - `fresh_request`: `0` (no `previous_response_id`).
  - `chained_user_followup`: `~2,000` tokens.
  - `tool_result_followup`: `~4,000` tokens base, plus `~1,000` tokens per
    chain-depth level (`FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`), capped at a
    fraction of the usable window (`FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`).
  - `summarization_followup`: `~2,000` tokens (compact input, no tools).

All values are deliberately round; treat them as starting points to log against,
not as validated thresholds.

## Tuning surface
This policy is intentionally tunable through the smallest viable set of knobs.
The split between measured and estimated reserves (above) is what keeps that
surface small.

### What is tunable
- `base_safety_ratio` — the global usable-window discount (default `0.85`).
- Hidden chain reserve — the per-request-class values and the per-chain-depth
  increment. This is the primary tuning target; it is the only estimated bucket.
- Top-level reserve — a flat envelope allowance (default `~256`); rarely changed.

### What is not tunable
- Tool schema reserve and structured payload reserve are **measured** per
  request, not configured. They have no knobs and must not be exposed as config
  — exposing them would reintroduce the over-trim margin the measured approach
  exists to eliminate.

### Where the knobs live
- The model input window is already config-driven: `MODEL_INPUT_WINDOW`, falling
  back to `MODEL_CONTEXT_WINDOW`, read from the `config` object.
- The tunable budget values above are **config fields with the documented
  defaults baked in**, not hardcoded module constants. This is a deliberate
  change from the current adapter, where `INPUT_WINDOW_SAFETY_RATIO = 0.85` and
  the `0.8` trim target are hardcoded. Concrete keys (see
  `src/monitor/config.yaml.example`):
  - `FOLLOWUP_BASE_SAFETY_RATIO` — `base_safety_ratio` (default `0.85`)
  - `FOLLOWUP_TOPLEVEL_RESERVE_TOKENS` — top-level reserve (default `256`)
  - `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS` — per-class hidden-chain reserve
  - `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH` / `_CAP_RATIO` — depth scaling and its cap
- Rationale: Phase 4 calibrates reserves **per model family**, and `MODEL` is
  already config-driven. Per-model tuning is only practical if the reserves can
  be set in config alongside the model selection, without editing source.

### Defaults and absence
- Each tunable field defaults to its starting constant when unset, so an
  untouched config reproduces today's effective behavior (modulo the
  measured-reserve correction).
- If no valid model input window is configured, strict admission control cannot
  run and the request is classified `unknown_budget` (see Admission outcomes),
  independent of any reserve tuning.

## Estimation requirements
### Visible payload estimation
Estimate the token cost of `input` using a structure-aware approach.

For tool-result follow-ups, the estimate should account for the full item shell, not just `output` text.

### Counting the measured reserves
The canonical `count_message_tokens(...)` is **not** suitable for the measured
reserves. By contract it counts only the `content` / `output` *text* of an item
and ignores the surrounding dict structure and any tool-schema payload, which is
precisely the overhead the measured reserves exist to capture.

Measured reserves must therefore be counted from the **serialized structure**:

- Add a dedicated structural-counting helper that token-counts
  `json.dumps(obj)` for the object being measured.
- Use it for:
  - the tool catalog (`tools` + `tool_choice`) — count the serialized schema
  - each `function_call_output` item **shell** — count the full serialized item,
    then subtract the already-counted `output` text to avoid double-counting, OR
    count shell-minus-output directly
- Do **not** extend or relax `count_message_tokens(...)` itself; its
  text-only contract is relied on elsewhere. The structural helper is a separate
  function, used only by the reserve calculator.

### Hidden overhead policy
Because `previous_response_id` introduces non-local context that cannot be measured exactly, the implementation must use explicit reserves rather than assume visible payload estimates are complete.

## Admission outcomes
### `send`
Visible payload fits within the computed payload budget.

### `send_trimmed`
Visible payload exceeds the budget, but can be trimmed to fit.

### `fallback`
Visible payload cannot be safely reduced enough, or no budget remains after reserves.

### `unknown_budget`
No valid model input window is available, so strict full-request admission control cannot run.

## Trimming rules
### Tool-result follow-ups
When trimming is required:
1. preserve item identity when possible
2. trim large `output` values first
3. preserve deterministic truncation markers
4. reduce low-priority items to stubs if necessary
5. fallback instead of sending if even minimal stubs do not fit

### Summarization follow-ups
Prefer:
- compact inputs
- no tools
- explicit instruction not to call more tools

## Fallback expectations
If a normal tool-result follow-up is unsafe, the caller should choose a smaller request shape, such as:
- summarization follow-up without tools
- fresh request rebase with concise summary
- minimal answer mode

Baseline Phase 3 behavior is to route the `fallback` outcome into the adapter's
existing summarization/rebase path. The other request shapes are compatible
variants, not prerequisites for the first fallback rollout.

## Logging requirements
Each budgeting pass should record:
- request class
- model input window
- usable window
- each reserve bucket
- original visible payload estimate
- final visible payload estimate
- number of tool-result items
- presence of `previous_response_id`
- presence of tools
- final decision

## Non-goals
This spec does not guarantee exact provider token parity. It defines a conservative admission-control strategy that reduces the probability of context-window overruns.
