# REQUEST_FLOW

## Purpose
Define the request-handling flow for long-running assistant sessions so the system can avoid context-window failures while preserving answer quality.

This flow combines:
- depth-aware reserve tuning
- pass/fail admission control
- compaction when a request is too large
- rebase fallback when compaction still does not fit
- graceful failure only when recovery paths are exhausted
- optional user-facing notes when compaction or rebase occurs
- a disabled-by-default hook for future tool omission hints

## Design goals
- Prevent provider-side `context_length_exceeded` failures when possible.
- Keep the decision model simple enough to implement and tune.
- Preserve the most important task state when context must be shortened.
- Avoid unnecessary round trips on ordinary short chains.
- Make long chains safer without over-penalizing normal sessions.
- Allow the implementation to choose between pass, compact, rebase, and graceful failure using a single linear flow.
- Keep tool omission architecturally possible without enabling it yet.
- Make user-facing notices optional, short, and tied only to meaningful recovery events.

## Core policy
The system uses a binary routing decision:
- **pass**: the request fits and can be sent
- **fail**: the request is too large and must be reduced before sending

There is no separate borderline state.

A dynamic hidden-context reserve is used to make the pass/fail decision more accurate as the chain grows.

## Reserve behavior
The hidden reserve grows with RT count.

Recommended starting shape:
- `RT <= 20` → reserve is `2,000`
- `RT >= 45` → reserve is `8,000`
- `20 < RT < 45` → linearly interpolate between `2,000` and `8,000`

Recommended implementation details:
- Use a pure helper that accepts RT count and returns an integer reserve.
- Keep the same reserve function for the compaction and rebase passes.
- Clamp the computed reserve to a reasonable maximum so it cannot consume the whole usable window.
- Treat the curve as tunable based on logs, not as a permanently fixed constant.

This makes the system conservative enough for long chains while keeping ordinary sessions efficient.

## Exact flow
1. Compute chain depth / RT count.
2. Compute the hidden reserve from RT count.
3. Estimate whether the follow-up fits with the reserve applied.
4. If it fits, send the request.
5. If it does not fit, compact the context.
6. Recompute the estimate.
7. If it now fits, send the request.
8. If it still does not fit, rebase the conversation.
9. Recompute the estimate again.
10. If it now fits, send the request.
11. If it still does not fit, fail gracefully.

### Exact pass/fail rule
The implementation should treat fit as a boolean result from the estimator.
- `true` means the request can be sent.
- `false` means the request must not be sent yet.

The estimator should account for:
- visible prompt content
- hidden reserve for the current RT count
- tool-schema or other structural overhead when applicable
- any other fixed request-shape overhead the adapter already knows about

The estimator does not need a borderline state.

## Compaction behavior
Compaction should:
- shorten the context
- preserve the current goal
- preserve the latest confirmed decisions
- preserve unresolved constraints
- remove redundant or noisy history
- keep enough recent context to continue the current task without re-asking obvious questions

### User feedback for compaction
If compaction changes the request path in a meaningful way, show a short note such as:
- “I’m condensing context to keep this thread reliable.”

### Compaction success criteria
Compaction is successful if the new payload estimate fits.
If compaction succeeds, the system should send the compacted request rather than escalate to rebase.
If compaction fails to reduce the request enough, continue to rebase.

## Rebase behavior
Rebase should:
- create a fresh condensed summary
- preserve the task goal
- preserve the essential constraints and decisions
- discard stale intermediate detail
- continue the task from the smaller summary
- be smaller than compaction output when possible, because its job is to create a new minimal working base

### User feedback for rebase
If rebase occurs, show a short note such as:
- “I’m continuing from a condensed summary to avoid context overflow.”

### Rebase success criteria
Rebase is successful if the rebased payload estimate fits.
If rebase succeeds, the system should send the rebased request.
If rebase fails, the system should stop and surface a graceful failure.

## Tool omission hook
The system should include a hook for future selective tool omission, but it must be disabled by default.

### Recommended current state
- Capability exists in the architecture.
- Feature flag is off.
- No behavior change is applied yet.
- The main flow ignores the hook unless it is explicitly enabled.

### Future use
A small local model could later classify whether a request is likely tool-oriented or conversational and return a hint such as:
- `tool_likely`
- `tool_unlikely`
- `tool_unknown`

The main router could then decide whether it is safe to omit large tool payloads.

### Tool-omission safety rule
If the hint is unavailable or low confidence, keep tools enabled.
If the request is clearly tool-oriented, do not omit tools.
Only omit tools when the request is clearly conversational and the feature flag is on.

## Failure behavior
If compaction and rebase both fail to bring the request under budget, the system should:
- stop trying to send the oversized request
- surface a graceful failure
- suggest a narrower scope or a smaller working summary if appropriate
- avoid leaking raw provider error details unless they are specifically useful for debugging

## Implementation notes
- Keep the flow linear and explicit.
- Use the same reserve function for compaction and rebase initially.
- Preserve more context in compaction than in rebase.
- Keep user-facing notices short and calm.
- Treat the reserve curve and thresholds as tunable values.

## Recommended defaults
- Depth-aware reserve ramp: yes
- Compaction notice: yes, brief
- Rebase notice: yes, brief
- Tool omission hook: yes, but disabled
- Same reserve function for all recovery paths: yes, initially
- Compaction preserves more context than rebase: yes

## Tunable item recommendations

### Interpolation curve between 20 and 45 RT
Use a linear interpolation.

- `RT <= 20` → `2,000`
- `RT >= 45` → `8,000`
- in between → linearly scale between those values

Why:
- easiest to implement
- easiest to reason about
- easiest to tune from logs
- predictable for users and developers

### Final wording for compaction/rebase notices
Keep them short and stable.

#### Compaction
- “I’m condensing context to keep this thread reliable.”

#### Rebase
- “I’m continuing from a condensed summary to avoid context overflow.”

Why:
- calm
- transparent
- not overly technical
- easy to reuse consistently

### Feature-flag name for tool omission
Use an explicit, narrow flag:

- `ENABLE_FOLLOWUP_TOOL_OMISSION_HINTS`

Why:
- clear intent
- easy to grep
- reads well in config
- unlikely to be confused with the main reserve logic

### Tool-omission helper design
Use a dedicated helper class, `UtilityLLM`, for the local Ollama-based hinting step.

Recommended shape:
- module: `utility_llm.py`
- class: `UtilityLLM`
- local endpoint: `127.0.0.1` Ollama
- init inputs: system prompt and user prompt, both configurable at construction time
- output: a stable enum such as `tool_likely`, `tool_unlikely`, or `unknown`
- fallback: return `unknown` if the local model call or parsing fails

Callback guidance:
- avoid a broad callback-based design unless needed later
- prefer a narrow optional parser callable if customization is necessary
- keep the main class responsible for transport and prompt execution

Why this is a good fit:
- keeps the helper reusable for future lightweight LLM tasks
- allows prompt reuse without hardcoding task-specific text into the class body
- keeps the main request-flow logic simple
- preserves a clean fallback path when the local model is unavailable

### Whether notices should be emitted directly or through a shared helper
For the MVP, emit directly from the adapter if that is where the decision is made.

If the notices grow beyond a single path, refactor to a shared helper later.

Why shared helper is better:
- consistent wording
- easier to suppress duplicates
- easier to test
- easier to change later

Why direct emission can still be okay:
- faster to implement
- fewer moving parts
- good for MVP if there is only one path

### Practical recommendation
- Linear interpolation
- Short stable notices
- `ENABLE_FOLLOWUP_TOOL_OMISSION_HINTS`
- `UtilityLLM` helper for local Ollama classification
- Prompts passed into the helper initializer
- Optional parser callable only if needed later
- Direct emission in MVP, helper later if needed

## Suggested source code to examine for context

### Primary implementation surface
- `src/monitor/core/llm_responses_adapter.py`
  - This is the main runtime path for Responses API follow-up budgeting, request classification, payload preflight, summarization fallback, and context-length failure logging.
  - Relevant areas include:
    - request-class classification around `classify_followup_request`
    - reserve/default handling near the hidden-chain reserve helpers
    - payload budgeting and decisioning around `budget_followup_request`
    - tool-result follow-up fallback routing near the existing summarization/rebase branch
    - provider `context_length_exceeded` logging and exception handling
  - This is the most likely place to implement:
    - dynamic RT-aware reserve computation
    - pass/fail admission logic
    - compaction/rebase routing behavior
    - user-facing compaction/rebase notices, if those notices are emitted from the adapter path

### Config and tunables
- `src/monitor/config.py`
  - Holds the current static defaults for:
    - `FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS`
    - `FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH`
    - `FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO`
    - `FOLLOWUP_BASE_SAFETY_RATIO`
  - This is where a new feature flag for optional tool omission or user-facing fallback notices would likely be declared.
  - It is also the first file to inspect when deciding whether the dynamic reserve should replace or layer on top of the current static `chained_user_followup` value.

### Existing compaction and telemetry context
- `src/monitor/lib/history.py`
  - Already contains compaction-policy commentary and telemetry derived from reserve-aware follow-up budgeting.
  - Useful for understanding how the system currently decides that hidden `previous_response_id` pressure should trigger compaction even when visible history still appears to fit.
  - Likely integration point if user-visible compaction state should be reflected in history or telemetry.

### Current user-facing error wording
- `src/monitor/lib/llm_utils.py`
  - Contains the current user-friendly translation for `context_length_exceeded` errors.
  - Inspect this when deciding how graceful failure messaging should differ from compaction/rebase notices.

### Tests to extend first
- `tests/monitor/core/test_llm_responses_adapter.py`
  - Primary test file for reserve-aware follow-up budgeting and fallback behavior.
  - This is the main place to add tests for:
    - RT-aware reserve growth from `2,000` to `8,000`
    - pass/fail behavior with no borderline state
    - compaction success path
    - rebase success path
    - graceful failure when both recovery steps fail
    - notice emission behavior for compaction and rebase
- `tests/monitor_oop/core/test_summarization_service.py`
  - Useful if the rebase/fallback path relies on existing summarization behavior.
- `tests/monitor_oop/core/infrastructure/test_request_capacity_service.py`
  - Useful if similar pass/fail capacity semantics are mirrored into the OOP service layer later.
- `tests/monitor_oop/core/infrastructure/test_rate_limit_service.py`
  - Useful reference for chain-aware token estimation behavior and cached `previous_response_id` baselines.

### OOP code to inspect for parity or future alignment
These files may not be the first implementation target, but they matter if the same flow later needs to exist in the OOP runtime:
- `src/monitor_oop/core/infrastructure/llm_response_client.py`
- `src/monitor_oop/core/infrastructure/request_capacity_service.py`
- `src/monitor_oop/core/infrastructure/rate_limit_service.py`
- `src/monitor_oop/core/llm_service.py`
- `src/monitor_oop/core/conversation_session.py`

These OOP files already contain:
- request-capacity preflight
- chain-aware token estimation via cached `previous_response_id` totals
- existing compaction/session behavior

If the feature is first implemented only in the classic adapter path, these files should still be reviewed to avoid semantic drift.

### Suggested implementation order
1. Inspect `src/monitor/core/llm_responses_adapter.py` and confirm the exact current budget decision states.
2. Inspect `src/monitor/config.py` to decide which values become dynamic and which remain static caps or defaults.
3. Inspect `src/monitor/lib/history.py` to understand current compaction triggers and reuse points.
4. Inspect `src/monitor/lib/llm_utils.py` to preserve friendly failure behavior.
5. Extend `tests/monitor/core/test_llm_responses_adapter.py` before changing runtime logic.

## Acceptance criteria
- The flow is linear and easy to reason about.
- The request is either passed or failed at each admission step.
- The reserve increases with RT count.
- Compaction happens before rebase.
- Rebase happens before graceful failure.
- User-facing notes are available for compaction and rebase.
- Tool omission is architecturally supported but off by default.
- The document points to the concrete source files that should be examined before implementation.
