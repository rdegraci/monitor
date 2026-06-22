# TOKEN_BUDGET Working Docs

This mini-set of cached docs captures the proposed design direction for safer Responses API follow-up budgeting.

## Files
- `PLAN_TOKEN_BUDGET.md`: implementation direction and phased approach
- `SPEC_TOKEN_BUDGET.md`: behavior and budgeting model
- `ROADMAP_TOKEN_BUDGET.md`: phased rollout guidance
- `CHECKLIST_TOKEN_BUDGET.md`: design and validation checklist

## Focus
These docs are centered on one architectural change:
- budget follow-up requests against the full effective request size rather than only visible tool-output text

## Main concerns addressed
- `context_length_exceeded` failures on tool-result follow-ups
- hidden request cost from `previous_response_id`
- tool schema overhead on follow-ups
- structured `function_call_output` payload overhead
- need for safer fallback behavior when normal follow-ups are too large
