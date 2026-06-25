# TOKEN_BUDGET Working Docs

This mini-set of cached docs captures the proposed design direction for safer Responses API follow-up budgeting.

## Files
- `PLAN_TOKEN_BUDGET.md`: implementation direction and phased approach
- `SPEC_TOKEN_BUDGET.md`: behavior and budgeting model
- `ROADMAP_TOKEN_BUDGET.md`: phased rollout guidance
- `CHECKLIST_TOKEN_BUDGET.md`: design and validation checklist
- `REQUEST_FLOW.md`: implemented follow-up flow, recovery behavior, and helper design notes

## Focus
These docs are centered on one architectural change:
- budget follow-up requests against the full effective request size rather than only visible tool-output text

## Current implementation state
The reserve-aware follow-up budgeting work is now implemented in
`src/monitor/core/llm_responses_adapter.py`.

Current behavior includes:
- request-shape classification for follow-up calls,
- a pure payload-budget calculator,
- config-driven base safety and hidden-chain reserves,
- measured tool-schema and structured payload reserves using serialized
  structure token counting,
- structured preflight logging,
- fallback into the existing summarization/rebase path when a normal tool
  follow-up is unsafe to send.

The remaining roadmap item is empirical tuning of hidden-chain reserves by model
family and observed chain depth.

## Main concerns addressed
- `context_length_exceeded` failures on tool-result follow-ups
- hidden request cost from `previous_response_id`
- tool schema overhead on follow-ups
- structured `function_call_output` payload overhead
- need for safer fallback behavior when normal follow-ups are too large
