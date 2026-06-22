# CHECKLIST_TOKEN_BUDGET

## Planning
- [x] Define the problem in terms of full effective request size, not only visible tool output.
- [x] Identify the major hidden cost sources: `previous_response_id`, tools, structured payload overhead, and envelope overhead.
- [x] Choose phased rollout rather than a one-shot replacement of existing trimming.

## Design
- [x] Define request classes for follow-up budgeting.
- [x] Define reserve buckets for hidden chain, tool schema, structured payload, and top-level overhead.
- [x] Mark tool-schema and structured-payload reserves as measured (counted exactly), and hidden-chain as the only estimated/tunable reserve.
- [x] Provide seed starting constants so Phase 1 is actionable.
- [x] Define admission outcomes: send, send_trimmed, fallback, unknown_budget.
- [x] Define logging expectations for budget decisions.

## Implementation guidance
- [ ] Phase 1: add a reserve-aware preflight helper as the single source of the follow-up budget.
- [ ] Phase 1: subsume (retire) the existing `0.85` safety ratio and `0.8` trim target instead of stacking the calculator on top of them.
- [ ] Phase 1: expose the budget computation as a pure, network-free function for unit testing.
- [ ] Phase 1: route both `INPUT_WINDOW_SAFETY_RATIO` sites (~line 643 and ~line 1644) through `FOLLOWUP_BASE_SAFETY_RATIO` so they cannot diverge.
- [ ] Phase 1: source the per-depth hidden-chain reserve from the existing `iteration` loop counter.
- [ ] Phase 2: measure tool-schema and `function_call_output` shell overhead exactly; estimate only the hidden-chain reserve.
- [ ] Phase 2: add a dedicated `json.dumps`-based structural-counting helper for the measured reserves; do not modify `count_message_tokens` (its text-only contract is relied on elsewhere).
- [ ] Phase 3: route the `fallback` outcome into the existing summarization/rebase path rather than reimplementing it.
- [ ] Phase 4: tune the hidden-chain reserve by model and chain depth if needed.

## Validation
- [ ] Confirm fewer `context_length_exceeded` failures on tool-result follow-ups.
- [ ] Confirm logs clearly explain budget allocation and decisions.
- [ ] Confirm trimming preserves enough semantic value for useful final answers.
- [ ] Confirm summarization or rebase fallbacks work when normal follow-ups are rejected.

## Follow-up
- [ ] Consolidate stable conclusions into primary documentation if the policy becomes a long-term part of the architecture.
